"""Build execution for one physical knowledge database.

A physical ``llm.store.database`` owns the backend lifecycle and one complete
build method.  This model remains as the execution/search compatibility layer
used by chunks and callers, but no longer represents or drops a backend
collection by itself.
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
    embedding_model_id = fields.Many2one(
        "llm.model",
        string="Embedding Model",
        related="database_id.embedding_model_id",
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
    is_default = fields.Boolean(
        default=False,
        help="Default database build used when no database is explicitly selected.",
    )
    state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("building", "Building"),
            ("vectorized", "Vectorized"),
            ("error", "Error"),
        ],
        default="draft",
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
        """Compatibility alias: provisioning belongs to the database."""
        self.ensure_one()
        return self.database_id.action_initialize()

    def action_drop(self):
        """Compatibility action that drops this build's physical database."""
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

    def insert_vectors(self, vectors, metadata=None, ids=None, **kwargs):
        self.ensure_one()
        return self.database_id.insert_vectors(
            vectors, metadata=metadata, ids=ids, **kwargs
        )

    # ------------------------------------------------------------------
    # Build: split (transient) -> embed -> insert, text travels as payload
    # ------------------------------------------------------------------
    def action_build(self, specific_document_ids=None):
        """Build the database from its configured collection and method."""
        for vector in self:
            vector.write({"state": "building"})
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
                vector.write({"state": "vectorized"})
                _logger.info(
                    "Database build '%s': embedded %d chunks from %d documents.",
                    vector.name,
                    total_chunks,
                    len(documents),
                )
            except Exception:
                _logger.exception("Database build failed for %s", vector.name)
                vector.write({"state": "error"})
                raise
        return True

    def _build_document(self, chunkset, document_record):
        """Split, embed and insert one document; return its chunk count."""
        self.ensure_one()
        chunk_texts = chunkset._split_document(document_record)
        if not chunk_texts:
            return 0
        chunks = chunkset._sync_chunk_pointers(document_record, chunk_texts)

        vectors = self.embedding_model_id.embedding(chunk_texts)
        if not vectors:
            return 0
        detected_dimension = len(vectors[0])
        if self.dimension and self.dimension != detected_dimension:
            raise UserError(
                _(
                    "Embedding model returned dimension %(actual)s, but database "
                    "'%(database)s' is configured for %(expected)s.",
                    actual=detected_dimension,
                    database=self.database_id.name,
                    expected=self.dimension,
                )
            )
        if not self.dimension:
            self.database_id.write({"dimension": detected_dimension})
        if self.database_id.state != "ready":
            self._initialize_store()

        document = document_record.get_processed_document()
        metadata_list = []
        for chunk, text in zip(chunks, chunk_texts):  # noqa: B905
            payload = dict(document["metadata"])
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
        self.insert_vectors(vectors=vectors, metadata=metadata_list, ids=chunks.ids)
        return len(chunks)
