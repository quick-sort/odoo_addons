"""Build execution for one logical vector database.

``llm.store.database`` owns the provider lifecycle, isolation scope, and one
complete build method. This model records build execution state and delegates
provider operations to that database.
"""

import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class LLMKnowledgeVector(models.Model):
    _name = "llm.knowledge.vector"
    _description = "LLM Knowledge Database Build"
    _inherit = ["mail.thread"]
    _order = "id"

    database_id = fields.Many2one(
        "llm.store.database",
        string="Store Database",
        required=True,
        ondelete="cascade",
        index=True,
        tracking=True,
    )
    name = fields.Char(related="database_id.name", store=True, readonly=True)
    chunkset_id = fields.Many2one(
        "llm.knowledge.chunkset",
        string="Chunking Configuration",
        related="database_id.chunkset_id",
        store=True,
        readonly=True,
        index=True,
    )
    collection_id = fields.Many2one(
        "llm.knowledge.collection",
        string="Knowledge Collection",
        related="database_id.knowledge_collection_id",
        store=True,
        readonly=True,
        index=True,
    )
    dense_embedding_model_id = fields.Many2one(
        "llm.model",
        string="Dense Embedding Model",
        related="database_id.dense_embedding_model_id",
        store=True,
        readonly=True,
    )
    sparse_embedding_model_id = fields.Many2one(
        "llm.model",
        string="Sparse Embedding Model",
        related="database_id.sparse_embedding_model_id",
        store=True,
        readonly=True,
    )
    store_id = fields.Many2one(
        "llm.store",
        string="Store Instance",
        related="database_id.store_id",
        store=True,
        readonly=True,
    )
    dimension = fields.Integer(related="database_id.dimension", readonly=True)
    vector_count = fields.Integer(related="database_id.vector_count", readonly=True)
    metadata = fields.Json(related="database_id.metadata", readonly=True)
    description = fields.Text(related="database_id.description", readonly=True)
    active = fields.Boolean(related="database_id.active", store=True, readonly=True)
    state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("building", "Building"),
            ("vectorized", "Vectorized"),
            ("error", "Error"),
        ],
        default="draft",
        required=True,
        copy=False,
        tracking=True,
    )

    _one_build_per_database = models.Constraint(
        "UNIQUE(database_id)",
        "A store database can have only one build configuration.",
    )

    @api.constrains("database_id", "collection_id", "chunkset_id")
    def _check_database_ownership(self):
        for vector in self:
            if (
                vector.database_id
                and vector.chunkset_id.collection_id != vector.collection_id
            ):
                raise UserError(
                    _("A database build cannot use another collection's chunkset.")
                )

    def _initialize_store(self):
        """Provision the database while keeping retrieval offline during builds."""
        self.ensure_one()
        return self.database_id.with_context(
            database_ready_state="building"
        ).action_initialize()

    def action_drop(self):
        """Compatibility action that drops this build's provider scope."""
        for vector in self:
            vector.database_id.action_drop()
        return True

    def delete_vectors(self, ids=None):
        self.ensure_one()
        return self.database_id.delete_vectors(ids=ids)

    def search_vectors(self, query_vector, limit=10, filter=None, **kwargs):
        self.ensure_one()
        return self.database_id.search_vectors(
            query_vector, limit=limit, filter=filter, **kwargs
        )

    def insert_vectors(
        self, vectors=None, sparse_vectors=None, metadata=None, ids=None, **kwargs
    ):
        self.ensure_one()
        return self.database_id.insert_vectors(
            vectors,
            sparse_vectors=sparse_vectors,
            metadata=metadata,
            ids=ids,
            **kwargs,
        )

    # ------------------------------------------------------------------
    # Build: split (transient) -> embed -> insert, text travels as payload
    # ------------------------------------------------------------------
    def action_build(self, specific_document_ids=None):
        """Build the database from its configured collection and method."""
        for vector in self:
            vector.write({"state": "building"})
            database = vector.database_id
            if database.state == "draft":
                database.write({"last_error": False})
            else:
                database.write({"state": "building", "last_error": False})
            try:
                chunkset = vector.chunkset_id
                documents = chunkset.collection_id.document_ids
                if specific_document_ids:
                    documents = documents.filtered(
                        lambda record: record.id in specific_document_ids
                    )
                documents = documents.filtered(
                    lambda record: record.state in ("processed", "chunked", "ready")
                )
                if not documents:
                    raise UserError(
                        _("No processed documents are available to build '%s'.", vector.name)
                    )

                # A configured dimension allows provisioning before the first
                # batch. Otherwise the first embedding batch infers it.
                if vector.dimension:
                    vector._initialize_store()

                total_chunks = 0
                for document_record in documents:
                    total_chunks += vector._build_document(chunkset, document_record)
                if not vector.store_id.database_exists(vector.database_id):
                    vector._initialize_store()
                vector.write({"state": "vectorized"})
                vector.database_id.write({"state": "ready", "last_error": False})
                _logger.info(
                    "Database build '%s': embedded %d chunks from %d documents.",
                    vector.name,
                    total_chunks,
                    len(documents),
                )
            except Exception as error:
                _logger.exception("Database build failed for %s", vector.name)
                vector.write({"state": "error"})
                vector.database_id.write(
                    {"state": "error", "last_error": str(error)}
                )
                raise
        return True

    def _build_document(self, chunkset, document_record):
        """Split, embed and insert one document; return its chunk count."""
        self.ensure_one()
        chunk_texts = chunkset._split_document(document_record)
        chunks = chunkset._sync_chunk_pointers(document_record, chunk_texts)
        if not chunk_texts:
            return 0

        dense_vectors = (
            self.dense_embedding_model_id.embedding(chunk_texts)
            if self.dense_embedding_model_id
            else None
        )
        sparse_vectors = (
            self.sparse_embedding_model_id.embedding(chunk_texts)
            if self.sparse_embedding_model_id
            else None
        )
        if self.dense_embedding_model_id and not dense_vectors:
            raise UserError(_("The dense embedding model returned no vectors."))
        if self.sparse_embedding_model_id and not sparse_vectors:
            raise UserError(_("The sparse embedding model returned no vectors."))

        if dense_vectors:
            detected_dimension = len(dense_vectors[0])
            if self.dimension and self.dimension != detected_dimension:
                raise UserError(
                    _(
                        "Dense embedding model returned dimension %(actual)s, but "
                        "database '%(database)s' is fixed at %(expected)s.",
                        actual=detected_dimension,
                        database=self.database_id.name,
                        expected=self.dimension,
                    )
                )
            if not self.dimension:
                self.database_id.write({"dimension": detected_dimension})
        if not self.database_id.store_id.database_exists(self.database_id):
            self._initialize_store()

        document = document_record.get_processed_document()
        metadata_list = []
        for chunk, text in zip(chunks, chunk_texts):  # noqa: B905
            payload = dict(document["metadata"])
            payload.update(chunk.metadata or {})
            payload.update(
                {
                    "text": text,
                    "title": document["title"],
                    "source_uri": document["source_uri"],
                    "mimetype": document["mimetype"],
                    "filename": document["filename"],
                    "checksum": document["checksum"],
                    "document_id": document_record.id,
                    "document_name": document_record.name,
                    "collection_id": document_record.collection_id.id,
                    "store_database_id": self.database_id.id,
                    "chunk_id": chunk.id,
                    "chunkset_id": chunkset.id,
                    "sequence": chunk.sequence,
                }
            )
            metadata_list.append(payload)
        self.insert_vectors(
            vectors=dense_vectors,
            sparse_vectors=sparse_vectors,
            metadata=metadata_list,
            ids=chunks.ids,
        )
        return len(chunks)
