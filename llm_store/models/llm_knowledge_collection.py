"""Add independently buildable physical databases to knowledge collections.

``llm.knowledge.collection`` owns logical source documents.  It may be built
into several ``llm.store.database`` records, each using a different chunking,
embedding or backend-index method so retrieval quality and performance can be
compared without mixing variants in one physical database.

The legacy ``embedding_model_id`` and ``store_id`` fields remain convenience
projections of ``default_database_id``.  New integrations should select or
create the database explicitly.
"""

import logging

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from .llm_document_chunker import DEFAULT_CHUNK_OVERLAP, DEFAULT_CHUNK_SIZE

_logger = logging.getLogger(__name__)

_DEFAULT_CHUNKSET_NAME = "Default"


class LLMKnowledgeCollection(models.Model):
    _inherit = "llm.knowledge.collection"

    embedding_model_id = fields.Many2one(
        "llm.model",
        string="Embedding Model",
        compute="_compute_default_vector_fields",
        inverse="_inverse_embedding_model_id",
        store=True,
        readonly=False,
        domain="[('model_use', '=', 'embedding')]",
        tracking=True,
        help="Compatibility projection of the embedding model used by this "
        "collection's default physical database.",
    )
    store_id = fields.Many2one(
        "llm.store",
        string="Store Instance",
        compute="_compute_default_vector_fields",
        inverse="_inverse_store_id",
        store=True,
        readonly=False,
        tracking=True,
        help="Compatibility projection of the default database's instance.",
    )
    default_database_id = fields.Many2one(
        "llm.store.database",
        string="Default Store Database",
        compute="_compute_default_vector_fields",
        inverse="_inverse_default_database_id",
        store=True,
        readonly=False,
        tracking=True,
        domain="[('knowledge_collection_id', '=', id)]",
        help="Default physical database used for retrieval when no build variant "
        "is selected explicitly.",
    )
    database_ids = fields.One2many(
        "llm.store.database",
        "knowledge_collection_id",
        string="Store Databases",
        help="Independent physical builds of this knowledge collection. Each "
        "database has its own chunking, embedding and index configuration.",
    )
    database_count = fields.Integer(compute="_compute_database_count")
    chunk_count = fields.Integer(
        string="Chunk Count",
        compute="_compute_chunk_count",
    )
    chunk_ids = fields.Many2many(
        "llm.store.chunk",
        string="Chunks (from Documents)",
        compute="_compute_chunk_ids",
        store=False,
        help="Chunks belonging to the documents included in this collection.",
    )
    chunkset_ids = fields.One2many(
        "llm.knowledge.chunkset",
        "collection_id",
        string="Chunking Configurations",
        help="A collection can hold several chunksets. Each physical store "
        "database selects one chunkset as part of its independently "
        "benchmarkable build method.",
    )
    chunkset_count = fields.Integer(compute="_compute_chunkset_count")
    vector_ids = fields.Many2many(
        "llm.knowledge.vector",
        string="Database Builds",
        compute="_compute_vector_ids",
        store=False,
    )
    vector_count = fields.Integer(compute="_compute_vector_count")

    default_chunk_size = fields.Integer(
        string="Default Chunk Size",
        default=DEFAULT_CHUNK_SIZE,
        required=True,
        help="Chunk size (characters) for this collection's default chunkset.",
        tracking=True,
    )
    default_chunk_overlap = fields.Integer(
        string="Default Chunk Overlap",
        default=DEFAULT_CHUNK_OVERLAP,
        required=True,
        help="Chunk overlap (characters) for this collection's default chunkset.",
        tracking=True,
    )
    default_splitter_type = fields.Selection(
        selection=[
            ("recursive", "Recursive"),
            ("token", "Token"),
            ("contextual", "Contextual"),
        ],
        string="Default Splitter",
        default="recursive",
        required=True,
        help="Splitter type for this collection's default chunkset "
        "('contextual' enables contextual-retrieval wrapping).",
        tracking=True,
    )

    @api.depends("document_ids.chunk_ids")
    def _compute_chunk_ids(self):
        for collection in self:
            collection.chunk_ids = collection.document_ids.mapped("chunk_ids")

    @api.depends("chunk_ids")
    def _compute_chunk_count(self):
        for collection in self:
            collection.chunk_count = len(collection.chunk_ids)

    @api.depends("chunkset_ids")
    def _compute_chunkset_count(self):
        for collection in self:
            collection.chunkset_count = len(collection.chunkset_ids)

    @api.depends("database_ids")
    def _compute_database_count(self):
        for collection in self:
            collection.database_count = len(collection.database_ids)

    @api.depends("chunkset_ids.vector_ids")
    def _compute_vector_ids(self):
        for collection in self:
            collection.vector_ids = collection.chunkset_ids.mapped("vector_ids")

    @api.depends("vector_ids")
    def _compute_vector_count(self):
        for collection in self:
            collection.vector_count = len(collection.vector_ids)

    @api.depends(
        "chunkset_ids.vector_ids.is_default",
        "chunkset_ids.vector_ids.database_id",
        "chunkset_ids.vector_ids.database_id.embedding_model_id",
        "chunkset_ids.vector_ids.database_id.store_id",
    )
    def _compute_default_vector_fields(self):
        for collection in self:
            vector = collection._get_default_vector()
            database = vector.database_id if vector else False
            collection.default_database_id = database
            collection.embedding_model_id = (
                database.embedding_model_id if database else False
            )
            collection.store_id = database.store_id if database else False

    def _inverse_embedding_model_id(self):
        for collection in self:
            collection._sync_default_chunkset_vector(
                embedding_model_id=collection.embedding_model_id.id
            )

    def _inverse_store_id(self):
        for collection in self:
            collection._sync_default_chunkset_vector(store_id=collection.store_id.id)

    def _inverse_default_database_id(self):
        for collection in self:
            database = collection.default_database_id
            if not database:
                continue
            if database.knowledge_collection_id != collection:
                raise ValidationError(
                    _("The default database must belong to this knowledge collection.")
                )
            current = collection._get_default_vector()
            target = database._ensure_vector()
            if current and current != target:
                current.is_default = False
            target.is_default = True

    # ------------------------------------------------------------------
    # Default chunkset/vector management (backs the convenience fields)
    # ------------------------------------------------------------------
    def _get_default_chunkset(self):
        self.ensure_one()
        return self.chunkset_ids.filtered("is_default")[:1]

    def _get_default_vector(self):
        self.ensure_one()
        return self.vector_ids.filtered("is_default")[:1]

    def _sync_default_chunkset_vector(self, embedding_model_id=None, store_id=None):
        """Maintain the legacy default fields by creating/updating a database.

        The physical database, not the vector execution record, owns the
        instance, chunking and embedding configuration.
        """
        self.ensure_one()
        model_id = (
            embedding_model_id
            if embedding_model_id is not None
            else self.embedding_model_id.id
        )
        store = store_id if store_id is not None else self.store_id.id

        chunkset = self._get_default_chunkset()
        if not chunkset and not (model_id or store):
            return False

        if not chunkset:
            splitter = self.env["llm.knowledge.splitter"].create(
                {
                    "name": _("%s - Default Splitter", self.name),
                    "splitter_type": self.default_splitter_type or "recursive",
                    "chunk_size": self.default_chunk_size,
                    "chunk_overlap": self.default_chunk_overlap,
                }
            )
            chunkset = self.env["llm.knowledge.chunkset"].create(
                {
                    "name": _DEFAULT_CHUNKSET_NAME,
                    "collection_id": self.id,
                    "splitter_id": splitter.id,
                    "is_default": True,
                }
            )
        else:
            chunkset.splitter_id.write(
                {
                    "splitter_type": self.default_splitter_type
                    or chunkset.splitter_id.splitter_type,
                    "chunk_size": self.default_chunk_size,
                    "chunk_overlap": self.default_chunk_overlap,
                }
            )

        vector = self._get_default_vector()
        if not vector and model_id and store:
            database = self.env["llm.store.database"].create(
                {
                    "name": _("%s - Default", self.name),
                    "store_id": store,
                    "knowledge_collection_id": self.id,
                    "chunkset_id": chunkset.id,
                    "embedding_model_id": model_id,
                }
            )
            self.env["llm.knowledge.vector"].create(
                {"database_id": database.id, "is_default": True}
            )
        elif vector:
            update_vals = {}
            if model_id and vector.embedding_model_id.id != model_id:
                update_vals["embedding_model_id"] = model_id
            if store and vector.store_id.id != store:
                update_vals["store_id"] = store
            if chunkset and vector.database_id.chunkset_id != chunkset:
                update_vals["chunkset_id"] = chunkset.id
            if update_vals:
                vector.database_id.write(update_vals)
                vector.write({"state": "draft"})
                self._reset_ready_documents(
                    success_message=_(
                        "Default database method changed. Reset {count} "
                        "documents for re-embedding."
                    )
                )
        return True

    def write(self, vals):
        chunking_fields = {
            "default_chunk_size",
            "default_chunk_overlap",
            "default_splitter_type",
        }
        needs_chunking_sync = bool(chunking_fields & set(vals))

        result = super().write(vals)

        if needs_chunking_sync:
            for collection in self:
                collection._sync_default_chunkset_vector(
                    embedding_model_id=collection.embedding_model_id.id,
                    store_id=collection.store_id.id,
                )

        return result

    def _reset_ready_documents(
        self, success_message="Reset {{count}} documents for re-embedding."
    ):
        """Finds ready documents, resets their state to 'chunked', and posts a message."""
        self.ensure_one()
        ready_documents = self.document_ids.filtered(lambda r: r.state == "ready")
        if ready_documents:
            count = len(ready_documents)
            ready_documents.write({"state": "chunked"})
            self._post_styled_message(
                success_message.format(count=count), message_type="info"
            )
            return count
        return 0

    def action_view_chunks(self):
        self.ensure_one()
        return {
            "name": _("Collection Chunks"),
            "view_mode": "list,form",
            "res_model": "llm.store.chunk",
            "domain": [("collection_id", "=", self.id)],
            "type": "ir.actions.act_window",
        }

    def action_view_chunksets(self):
        self.ensure_one()
        return {
            "name": _("Chunking Configurations"),
            "view_mode": "list,form",
            "res_model": "llm.knowledge.chunkset",
            "domain": [("collection_id", "=", self.id)],
            "type": "ir.actions.act_window",
            "context": {"default_collection_id": self.id},
        }

    def action_view_databases(self):
        self.ensure_one()
        return {
            "name": _("Knowledge Store Databases"),
            "view_mode": "list,form",
            "res_model": "llm.store.database",
            "domain": [("knowledge_collection_id", "=", self.id)],
            "type": "ir.actions.act_window",
            "context": {"default_knowledge_collection_id": self.id},
        }

    def reindex_collection(self):
        """Drop each physical database once and queue its documents to rebuild."""
        for collection in self:
            if not collection.database_ids:
                collection._post_styled_message(
                    _("No store databases are configured for this collection."),
                    message_type="info",
                )
                continue

            for database in collection.database_ids:
                try:
                    database.action_drop()
                except Exception as error:  # noqa: BLE001
                    collection._post_styled_message(
                        _(
                            "Error resetting database '%(database)s': %(error)s",
                            database=database.name,
                            error=str(error),
                        ),
                        message_type="error",
                    )

            reset_count = collection._reset_ready_documents(
                success_message=_(
                    "Reset {count} documents for re-embedding across "
                    f"{len(collection.database_ids)} database variant(s)."
                )
            )
            if not reset_count:
                collection._post_styled_message(
                    _("No ready documents found to reindex."), message_type="info"
                )

    def action_embed_documents(self, specific_document_ids=None):
        """Action handler for embedding documents in the UI."""
        self.ensure_one()
        result = self.embed_documents(specific_document_ids=specific_document_ids)

        if result and result.get("success"):
            return True
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Embedding Failed"),
                "message": _("Failed to embed documents. Check the logs for details."),
                "type": "warning",
                "sticky": False,
            },
        }

    def embed_documents(self, specific_document_ids=None, batch_size=50):
        """Build every configured physical database for this collection."""
        overall_success = False
        processed_chunks_total = 0
        processed_documents = set()

        for collection in self:
            collection_success = False
            if not collection.vector_ids:
                collection._post_styled_message(
                    _(
                        "No store database found for this collection. Create a "
                        "database build with a chunking and embedding method first."
                    ),
                    message_type="warning",
                )
                continue

            documents = collection.document_ids
            if specific_document_ids:
                documents = documents.filtered(lambda r: r.id in specific_document_ids)
            documents = documents.filtered(lambda r: r.state in ("chunked", "ready"))

            if not documents:
                collection._post_styled_message(
                    _("No chunked documents found to embed."), message_type="info"
                )
                continue

            for vector in collection.vector_ids:
                try:
                    vector.action_build(specific_document_ids=documents.ids)
                    collection_success = True
                    overall_success = True
                    processed_documents.update(documents.ids)
                    processed_chunks_total += len(vector.chunkset_id.chunk_ids)
                except Exception as error:  # noqa: BLE001
                    collection._post_styled_message(
                        _(
                            "Error building database '%(database)s': %(error)s",
                            database=vector.database_id.name,
                            error=str(error),
                        ),
                        message_type="error",
                    )

            if collection_success:
                documents.write({"state": "ready"})
                collection._post_styled_message(
                    _(
                        "Successfully embedded %(documents)d documents across "
                        "%(databases)d database variant(s).",
                        documents=len(documents),
                        databases=len(collection.vector_ids),
                    ),
                    message_type="success",
                )

        return {
            "success": overall_success,
            "processed_chunks": processed_chunks_total,
            "processed_documents": len(processed_documents),
        }

    def _handle_removed_documents(self, removed_document_ids):
        """Remove all backend vectors before discarding document pointers."""
        result = super()._handle_removed_documents(removed_document_ids)
        if removed_document_ids:
            documents = self.env["llm.document"].browse(removed_document_ids)
            for document in documents:
                self._handle_document_removal(document)
        return result

    def _handle_document_removal(self, document):
        """Delete pointers once; their unlink hook cleans every database."""
        self.ensure_one()
        chunks = self.env["llm.store.chunk"].search(
            [("document_id", "=", document.id)]
        )
        if chunks:
            chunks.unlink()
            _logger.info(
                "Removed %d chunk pointers and their database vectors for document %s",
                len(chunks),
                document.id,
            )
        return True
