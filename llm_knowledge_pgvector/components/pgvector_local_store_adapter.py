"""In-Odoo pgvector implementation for llm.knowledge.vector configurations."""

import logging

from pgvector import Vector
from pgvector.psycopg2 import register_vector

from odoo import _
from odoo.exceptions import UserError

from odoo.addons.component.core import Component

_logger = logging.getLogger(__name__)

EMBEDDING_TABLE = "llm_knowledge_chunk_embedding"
MAX_VECTOR_DIMS = 2000
MAX_HALFVEC_DIMS = 4000
DISTANCE_OPERATORS = ("<=>", "<->", "<#>")
DEFAULT_OPERATOR = "<=>"


class PgvectorLocalStoreAdapter(Component):
    _name = "pgvector.local.store.adapter"
    _inherit = "llm.store.adapter"
    _usage = "pgvector_local"

    def sanitize_collection_name(self, store, name):
        return name

    def collection_exists(self, store, name, **kwargs):
        return True

    @staticmethod
    def _vector_config(store, vector_id):
        return store.env["llm.knowledge.vector"].browse(vector_id).exists()

    def create_collection(
        self, store, collection_id, dimension=None, metadata=None, **kwargs
    ):
        vector = self._vector_config(store, collection_id)
        if not vector:
            return False
        self._create_vector_index(
            store, vector.embedding_model_id.id, dimensions=dimension or vector.dimension
        )
        return True

    def delete_collection(self, store, collection_id, **kwargs):
        vector = self._vector_config(store, collection_id)
        if not vector:
            return True
        store.env["llm.knowledge.chunk.embedding"].search(
            [("vector_id", "=", vector.id)]
        ).unlink()
        return True

    def insert_vectors(
        self,
        store,
        collection_id,
        vectors,
        metadata=None,
        ids=None,
        **kwargs,
    ):
        if not ids or len(ids) != len(vectors):
            raise UserError(_("Must provide chunk IDs matching the vectors"))
        if metadata is not None and len(metadata) != len(vectors):
            raise UserError(_("Vector metadata must match the vector count"))
        vector = self._vector_config(store, collection_id)
        if not vector:
            return False
        model_id = vector.embedding_model_id.id
        self._unlink_embeddings(store, ids, vector.id)
        payloads = metadata or [{} for _item in vectors]
        values = []
        for chunk_id, embedding, payload in zip(ids, vectors, payloads):  # noqa: B905
            payload = dict(payload or {})
            values.append(
                {
                    "chunk_id": chunk_id,
                    "vector_id": vector.id,
                    "embedding_model_id": model_id,
                    "embedding": embedding,
                    "content": payload.get("text", ""),
                    "metadata": payload,
                }
            )
        if values:
            store.env["llm.knowledge.chunk.embedding"].create(values)
        dimensions = len(vectors[0]) if vectors else vector.dimension
        self._create_vector_index(store, model_id, dimensions=dimensions)
        return True

    def delete_vectors(self, store, collection_id, ids, **kwargs):
        vector = self._vector_config(store, collection_id)
        if not vector or ids is None:
            return False
        self._unlink_embeddings(store, ids, vector.id)
        return True

    @staticmethod
    def _unlink_embeddings(store, chunk_ids, vector_id):
        if chunk_ids:
            store.env["llm.knowledge.chunk.embedding"].search(
                [("chunk_id", "in", chunk_ids), ("vector_id", "=", vector_id)]
            ).unlink()

    def search_vectors(
        self,
        store,
        collection_id,
        query_vector,
        limit=10,
        filter=None,  # noqa: A002
        offset=0,
        query_operator=DEFAULT_OPERATOR,
        min_similarity=0.5,
        **kwargs,
    ):
        if query_operator not in DISTANCE_OPERATORS:
            raise UserError(
                _(
                    "Unknown distance operator '%(operator)s'. Expected one of: %(known)s",
                    operator=query_operator,
                    known=", ".join(DISTANCE_OPERATORS),
                )
            )
        vector = self._vector_config(store, collection_id)
        if not vector:
            return []

        register_vector(store.env.cr._cnx)
        vector_string = Vector._to_db(query_vector)
        query = f"""
            WITH query_vector AS (SELECT '{vector_string}'::vector AS vec)
            SELECT e.chunk_id,
                   1 - (e.embedding {query_operator} query_vector.vec) AS score,
                   e.content,
                   e.metadata
              FROM {EMBEDDING_TABLE} e
              JOIN llm_store_chunk c ON e.chunk_id = c.id
              JOIN llm_document d ON c.document_id = d.id
              CROSS JOIN query_vector
             WHERE e.vector_id = %s
               AND d.collection_id = %s
               AND d.state = 'ready'
               AND c.chunkset_id = %s
               AND e.embedding IS NOT NULL
               AND (1 - (e.embedding {query_operator} query_vector.vec)) >= %s
             ORDER BY score DESC
             LIMIT %s OFFSET %s
        """
        store.env.cr.execute(
            query,
            (
                vector.id,
                vector.collection_id.id,
                vector.chunkset_id.id,
                min_similarity,
                limit,
                offset,
            ),
        )
        results = []
        for chunk_id, score, content, metadata in store.env.cr.fetchall():
            payload = dict(metadata or {})
            payload["text"] = content or payload.get("text", "")
            results.append({"id": chunk_id, "score": score, "metadata": payload})
        return results

    @staticmethod
    def _get_index_name(table_name, embedding_model_id):
        return f"{table_name}_emb_model_{embedding_model_id}_idx"

    def _create_vector_index(
        self, store, embedding_model_id, dimensions=None, force=False
    ):
        if not dimensions and embedding_model_id:
            dimensions = self._probe_dimensions(store, embedding_model_id)
        cr = store.env.cr
        register_vector(cr._cnx)
        index_name = self._get_index_name(EMBEDDING_TABLE, embedding_model_id)
        if force:
            cr.execute(f"DROP INDEX IF EXISTS {index_name}")
        else:
            cr.execute("SELECT 1 FROM pg_indexes WHERE indexname = %s", (index_name,))
            if cr.fetchone():
                return True
        if dimensions and dimensions > MAX_HALFVEC_DIMS:
            _logger.warning(
                "Embedding model %s exceeds pgvector's indexing limit; using full scan.",
                embedding_model_id,
            )
            return False
        vector_type = "halfvec" if (dimensions or 0) > MAX_VECTOR_DIMS else "vector"
        dimension_spec = f"({dimensions})" if dimensions else ""
        operator_class = f"{vector_type}_cosine_ops"
        method = store.pgvector_index_method or "ivfflat"
        try:
            if method == "hnsw":
                try:
                    self._create_index_sql(
                        cr,
                        "hnsw",
                        index_name,
                        vector_type,
                        dimension_spec,
                        operator_class,
                        embedding_model_id,
                    )
                except Exception:  # noqa: BLE001
                    self._create_index_sql(
                        cr,
                        "ivfflat",
                        index_name,
                        vector_type,
                        dimension_spec,
                        operator_class,
                        embedding_model_id,
                    )
            else:
                self._create_index_sql(
                    cr,
                    "ivfflat",
                    index_name,
                    vector_type,
                    dimension_spec,
                    operator_class,
                    embedding_model_id,
                )
            return True
        except Exception as error:  # noqa: BLE001
            _logger.error("Error creating vector index: %s", error)
            return False

    @staticmethod
    def _probe_dimensions(store, embedding_model_id):
        model = store.env["llm.model"].browse(embedding_model_id)
        sample = model.embedding("") if model.exists() else []
        return len(sample[0]) if sample and sample[0] else None

    @staticmethod
    def _create_index_sql(
        cr,
        method,
        index_name,
        vector_type,
        dimension_spec,
        operator_class,
        embedding_model_id,
    ):
        savepoint = f"sp_{index_name}"
        cr.execute(f"SAVEPOINT {savepoint}")
        try:
            cr.execute(
                f"""
                CREATE INDEX {index_name} ON {EMBEDDING_TABLE}
                USING {method}((embedding::{vector_type}{dimension_spec}) {operator_class})
                WHERE embedding_model_id = %s AND embedding IS NOT NULL
                """,
                (embedding_model_id,),
            )
        except Exception:
            cr.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
            raise
        finally:
            cr.execute(f"RELEASE SAVEPOINT {savepoint}")

    def _drop_vector_index(self, store, embedding_model_id=None):
        cr = store.env.cr
        if embedding_model_id:
            cr.execute(
                f"DROP INDEX IF EXISTS {self._get_index_name(EMBEDDING_TABLE, embedding_model_id)}"
            )
            return True
        cr.execute("SELECT indexname FROM pg_indexes WHERE tablename = %s", (EMBEDDING_TABLE,))
        for (index_name,) in cr.fetchall():
            if "emb_model_" in index_name:
                cr.execute(f"DROP INDEX IF EXISTS {index_name}")
        return True
