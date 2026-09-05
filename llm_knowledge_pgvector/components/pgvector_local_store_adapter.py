"""In-Odoo vector storage as the ``llm.store`` service ``pgvector_local``.

Unlike the external adapters, this one operates on Odoo's *own* database: the
vectors live in the ``llm_knowledge_chunk_embedding`` table through the
``PgVector`` ORM field from ``base_pgvector``, and every statement runs on
``store.env.cr``.

That coupling is the point -- it is what buys transactional writes, cascade
deletes and single-query filtering -- but it has two consequences:

- **never wrap a connection or transaction around ``llm.store.work_on()``.**
  The SQL below assumes ``store.env.cr`` is the live Odoo cursor, and the
  savepoints in :meth:`_create_vector_index` are taken on it. Managing a
  separate connection in ``work_on`` (as the ``component`` addon's own
  docstring demonstrates) would silently break index creation and rollback.
- Odoo's database must have the pgvector extension, which needs a superuser to
  run ``CREATE EXTENSION vector`` once.

Two contracts are deliberately not overridden: ``list_collections`` (there are
no separate collections here -- everything lives in one Odoo table) and
``create_index`` (indexes are created implicitly by :meth:`create_collection`
and :meth:`insert_vectors`). Both inherit the ``llm.store.adapter`` stub and
raise ``NotImplementedError`` if dispatched. Nothing on ``llm.store`` probes
them with ``_has_service_method`` before dispatch, so this adapter is formally
incomplete rather than selectively capable.

TODO, DEFERRED TO THE llm_knowledge REWORK -- withdraw this from ``llm.store``
altogether. Its natural access path is the ``llm.knowledge.chunk.embedding``
model: it has no connection to manage and no remote to reach, none of which the
store contract models.
"""

import logging

from pgvector import Vector
from pgvector.psycopg2 import register_vector

from odoo import _
from odoo.exceptions import UserError

from odoo.addons.component.core import Component

_logger = logging.getLogger(__name__)

EMBEDDING_TABLE = "llm_knowledge_chunk_embedding"

# pgvector can build an ANN index on the plain 'vector' type up to 2000
# dimensions (Postgres 8KB page-size constraint on float4 storage). 'halfvec'
# raises the ceiling to 4000 dims (half precision) at some cost in accuracy.
# Beyond 4000 there is no indexable type at all.
MAX_VECTOR_DIMS = 2000
MAX_HALFVEC_DIMS = 4000

# Distance operators, whitelisted because they are interpolated into SQL.
DISTANCE_OPERATORS = ("<=>", "<->", "<#>")
DEFAULT_OPERATOR = "<=>"


class PgvectorLocalStoreAdapter(Component):
    _name = "pgvector.local.store.adapter"
    _inherit = "llm.store.adapter"
    _usage = "pgvector_local"

    # ------------------------------------------------------------------
    # Collections
    #
    # There is no real collection concept here: an "llm.knowledge.collection"
    # maps to rows filtered by embedding_model_id in one shared Odoo table. The
    # contract methods therefore mostly manage indexes.
    # ------------------------------------------------------------------

    def sanitize_collection_name(self, store, name):
        """No-op: collection names are never used as identifiers here."""
        return name

    def collection_exists(self, store, name, **kwargs):
        """Always true: the backing Odoo table always exists."""
        return True

    def create_collection(
        self,
        store,
        collection_id,
        dimension=None,
        metadata=None,
        **kwargs,
    ):
        """Ensure the vector index for the collection's embedding model."""
        collection = store.env["llm.knowledge.collection"].browse(collection_id)
        if not collection.exists():
            _logger.warning("Collection %s does not exist", collection_id)
            return False

        if collection.embedding_model_id:
            self._create_vector_index(store, collection.embedding_model_id.id)

        return True

    def delete_collection(self, store, collection_id, **kwargs):
        """Drop the collection's index and the embeddings only it referenced."""
        collection = store.env["llm.knowledge.collection"].browse(collection_id)
        if not collection.exists():
            return True

        embedding_model_id = (
            collection.embedding_model_id.id if collection.embedding_model_id else False
        )
        if not embedding_model_id:
            return True

        self._drop_vector_index(store, embedding_model_id)

        chunks = store.env["llm.store.chunk"].search(
            [("collection_ids", "in", [collection_id])],
        )
        chunk_ids = self._chunks_exclusive_to(chunks, collection, embedding_model_id)
        self._unlink_embeddings(store, chunk_ids, embedding_model_id)

        return True

    # ------------------------------------------------------------------
    # Vectors
    # ------------------------------------------------------------------

    def insert_vectors(
        self,
        store,
        collection_id,
        vectors,
        metadata=None,
        ids=None,
        **kwargs,
    ):
        """Replace the embeddings of ``ids`` for the collection's model."""
        if not ids or len(ids) != len(vectors):
            raise UserError(_("Must provide chunk IDs matching the vectors"))

        collection = store.env["llm.knowledge.collection"].browse(collection_id)
        if not collection.exists() or not collection.embedding_model_id:
            return False

        embedding_model_id = collection.embedding_model_id.id
        Embedding = store.env["llm.knowledge.chunk.embedding"]

        # Replace rather than update: simpler than diffing, and the unique
        # constraint on (chunk_id, embedding_model_id) would reject duplicates.
        self._unlink_embeddings(store, ids, embedding_model_id)

        vals_list = [
            {
                "chunk_id": chunk_id,
                "embedding_model_id": embedding_model_id,
                "embedding": vector,
            }
            for chunk_id, vector in zip(ids, vectors)  # noqa: B905
        ]
        if vals_list:
            Embedding.create(vals_list)

        self._create_vector_index(store, embedding_model_id)

    def delete_vectors(self, store, collection_id, ids, **kwargs):
        """Delete embeddings for ``ids``, sparing chunks shared with others."""
        if ids is None:
            return False

        collection = store.env["llm.knowledge.collection"].browse(collection_id)
        if not collection.exists() or not collection.embedding_model_id:
            return False

        embedding_model_id = collection.embedding_model_id.id
        chunks = store.env["llm.store.chunk"].browse(ids)
        chunk_ids = self._chunks_exclusive_to(chunks, collection, embedding_model_id)
        self._unlink_embeddings(store, chunk_ids, embedding_model_id)

        return True

    @staticmethod
    def _chunks_exclusive_to(chunks, collection, embedding_model_id):
        """Ids of ``chunks`` no other collection needs for this model.

        A chunk shared with another collection using the same embedding model
        must keep its embedding, otherwise that collection loses its vectors.
        """
        exclusive = []
        for chunk in chunks:
            other_collections = chunk.collection_ids - collection
            if not any(
                c.embedding_model_id.id == embedding_model_id
                for c in other_collections
            ):
                exclusive.append(chunk.id)
        return exclusive

    @staticmethod
    def _unlink_embeddings(store, chunk_ids, embedding_model_id):
        if not chunk_ids:
            return
        store.env["llm.knowledge.chunk.embedding"].search(
            [
                ("chunk_id", "in", chunk_ids),
                ("embedding_model_id", "=", embedding_model_id),
            ],
        ).unlink()

    def search_vectors(
        self,
        store,
        collection_id,
        query_vector,
        limit=10,
        filter=None,  # noqa: A002 - name kept for the llm.store contract
        offset=0,
        query_operator=DEFAULT_OPERATOR,
        min_similarity=0.5,
        **kwargs,
    ):
        """Cosine-similarity search joined against the knowledge tables.

        The join is the advantage of storing vectors in Odoo: the collection
        filter is applied in the same statement, with no second round trip.

        Returns:
            list of ``{"id", "score", "metadata"}`` dicts, best first.
        """
        if query_operator not in DISTANCE_OPERATORS:
            raise UserError(
                _(
                    "Unknown distance operator '%(operator)s'. Expected one of: "
                    "%(known)s",
                    operator=query_operator,
                    known=", ".join(DISTANCE_OPERATORS),
                ),
            )

        collection = store.env["llm.knowledge.collection"].browse(collection_id)
        if not collection.exists() or not collection.embedding_model_id:
            return []

        embedding_model_id = collection.embedding_model_id.id
        cr = store.env.cr

        register_vector(cr._cnx)
        vector_str = Vector._to_db(query_vector)

        index_name = self._get_index_name(EMBEDDING_TABLE, embedding_model_id)
        index_hint = f"/*+ IndexScan({EMBEDDING_TABLE} {index_name}) */"

        # NOTE: vector_str is interpolated rather than bound. It is built by
        # Vector._to_db from a float sequence, so it cannot carry SQL, but
        # binding it as a parameter would be cleaner. Left as-is to keep this
        # migration mechanical.
        query = f"""
            WITH query_vector AS (
                SELECT '{vector_str}'::vector AS vec
            )
            SELECT {index_hint} e.chunk_id,
                   1 - (e.embedding {query_operator} query_vector.vec) as score
            FROM {EMBEDDING_TABLE} e
            JOIN llm_store_chunk c ON e.chunk_id = c.id
            JOIN llm_knowledge_resource_collection_rel rel
                 ON c.resource_id = rel.resource_id
            CROSS JOIN query_vector
            WHERE rel.collection_id = %s
              AND e.embedding_model_id = %s
              AND e.embedding IS NOT NULL
              AND (1 - (e.embedding {query_operator} query_vector.vec)) >= %s
            ORDER BY score DESC
            LIMIT %s
            OFFSET %s
        """

        cr.execute(
            query,
            (collection_id, embedding_model_id, min_similarity, limit, offset),
        )

        return [
            {"id": chunk_id, "score": score, "metadata": {}}
            for chunk_id, score in cr.fetchall()
        ]

    # ------------------------------------------------------------------
    # Index management
    # ------------------------------------------------------------------

    @staticmethod
    def _get_index_name(table_name, embedding_model_id):
        return f"{table_name}_emb_model_{embedding_model_id}_idx"

    def _create_vector_index(
        self,
        store,
        embedding_model_id,
        dimensions=None,
        force=False,
    ):
        """Create the partial ANN index for one embedding model."""
        if not dimensions and embedding_model_id:
            dimensions = self._probe_dimensions(store, embedding_model_id)

        cr = store.env.cr
        register_vector(cr._cnx)
        index_name = self._get_index_name(EMBEDDING_TABLE, embedding_model_id)

        if force:
            cr.execute(f"DROP INDEX IF EXISTS {index_name}")
        else:
            cr.execute(
                "SELECT 1 FROM pg_indexes WHERE indexname = %s",
                (index_name,),
            )
            if cr.fetchone():
                _logger.info("Index %s already exists, skipping creation", index_name)
                return True

        if dimensions and dimensions > MAX_HALFVEC_DIMS:
            _logger.warning(
                "Embedding model %s produces %s-dimensional vectors, which "
                "exceeds pgvector's indexing limit (%s, via halfvec). Skipping "
                "index creation for this model; similarity search will fall "
                "back to a full scan.",
                embedding_model_id,
                dimensions,
                MAX_HALFVEC_DIMS,
            )
            return False

        vector_type = "halfvec" if (dimensions or 0) > MAX_VECTOR_DIMS else "vector"
        ops_class = f"{vector_type}_cosine_ops"
        dim_spec = f"({dimensions})" if dimensions else ""
        index_method = store.pgvector_index_method or "ivfflat"

        try:
            if index_method == "hnsw":
                try:
                    self._create_index_sql(
                        cr, "hnsw", index_name, vector_type, dim_spec,
                        ops_class, embedding_model_id,
                    )
                except Exception as err:  # noqa: BLE001 - probed capability
                    _logger.warning(
                        "HNSW index not supported, falling back to IVFFlat: %s",
                        err,
                    )
                    self._create_index_sql(
                        cr, "ivfflat", index_name, vector_type, dim_spec,
                        ops_class, embedding_model_id,
                    )
            else:
                self._create_index_sql(
                    cr, "ivfflat", index_name, vector_type, dim_spec,
                    ops_class, embedding_model_id,
                )

            _logger.info(
                "Created %s vector index %s for embedding model %s",
                vector_type,
                index_name,
                embedding_model_id,
            )
            return True
        except Exception as err:  # noqa: BLE001 - index is an optimisation
            _logger.error("Error creating vector index: %s", err)
            return False

    @staticmethod
    def _probe_dimensions(store, embedding_model_id):
        """Learn the vector size by asking the model for one embedding."""
        embedding_model = store.env["llm.model"].browse(embedding_model_id)
        if not embedding_model.exists():
            return None
        sample = embedding_model.embedding("")
        return len(sample[0]) if sample and sample[0] else None

    @staticmethod
    def _create_index_sql(
        cr,
        method,
        index_name,
        vector_type,
        dim_spec,
        ops_class,
        embedding_model_id,
    ):
        """Run one CREATE INDEX inside its own SAVEPOINT.

        Without the savepoint a failure (unsupported method or dimension)
        aborts the surrounding transaction, and every later query on this
        cursor -- including the embeddings just inserted -- fails with
        "current transaction is aborted".
        """
        savepoint = f"sp_{index_name}"
        cr.execute(f"SAVEPOINT {savepoint}")
        try:
            cr.execute(
                f"""
                CREATE INDEX {index_name} ON {EMBEDDING_TABLE}
                USING {method}((embedding::{vector_type}{dim_spec}) {ops_class})
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
        """Drop one model's index, or every embedding-model index."""
        cr = store.env.cr

        if embedding_model_id:
            index_name = self._get_index_name(EMBEDDING_TABLE, embedding_model_id)
            cr.execute(f"DROP INDEX IF EXISTS {index_name}")
            _logger.info("Dropped vector index %s", index_name)
            return True

        cr.execute(
            "SELECT indexname FROM pg_indexes WHERE tablename = %s",
            (EMBEDDING_TABLE,),
        )
        for (indexname,) in cr.fetchall():
            if "emb_model_" in indexname:
                cr.execute(f"DROP INDEX IF EXISTS {indexname}")
                _logger.info("Dropped vector index %s", indexname)
        return True
