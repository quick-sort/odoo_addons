"""Connect logical knowledge collections to independently built databases.

``llm.knowledge.collection`` owns source documents and may select one explicit
``default_database_id`` for retrieval. Store-instance, embedding, chunking, and
backend-index configuration belong only to each ``llm.store.database``; the
collection never projects or auto-creates those settings.
"""

import logging

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

from .llm_document_chunker import DEFAULT_CHUNK_OVERLAP, DEFAULT_CHUNK_SIZE

_logger = logging.getLogger(__name__)


class LLMKnowledgeCollection(models.Model):
    _inherit = "llm.knowledge.collection"

    default_database_id = fields.Many2one(
        "llm.store.database",
        string="Default Store Database",
        ondelete="set null",
        copy=False,
        tracking=True,
        domain="[('knowledge_collection_id', '=', id)]",
        help="Database used for retrieval when no build variant is selected "
        "explicitly. Its store and retrieval configuration remain owned by "
        "the database.",
    )
    database_ids = fields.One2many(
        "llm.store.database",
        "knowledge_collection_id",
        string="Vector Databases",
        help="Logical vector databases indexing this collection. Each owns its "
        "embedding, isolation, index, and query configuration.",
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
        help="A collection can hold several chunksets. Each logical vector "
        "database selects one chunkset as its benchmarkable splitting method.",
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
        ],
        string="Default Splitter",
        default="recursive",
        required=True,
        help="Splitter type for this collection's default chunkset. Contextual "
        "splitters require an explicit splitter record and chat model.",
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

    @api.constrains("default_chunk_size", "default_chunk_overlap")
    def _check_default_chunking_values(self):
        for collection in self:
            if collection.default_chunk_size <= 0:
                raise ValidationError(_("Default chunk size must be positive."))
            if (
                collection.default_chunk_overlap < 0
                or collection.default_chunk_overlap >= collection.default_chunk_size
            ):
                raise ValidationError(
                    _(
                        "Default chunk overlap must be non-negative and smaller "
                        "than default chunk size."
                    )
                )

    @api.constrains("default_database_id")
    def _check_default_database(self):
        for collection in self:
            database = collection.default_database_id
            if database and database.knowledge_collection_id != collection:
                raise ValidationError(
                    _("The default database must belong to this knowledge collection.")
                )

    def _get_default_chunkset(self):
        self.ensure_one()
        return self.chunkset_ids.filtered("is_default")[:1]

    def write(self, vals):
        chunking_fields = {
            "default_chunk_size",
            "default_chunk_overlap",
            "default_splitter_type",
        }
        needs_chunking_sync = bool(chunking_fields.intersection(vals))
        result = super().write(vals)

        if needs_chunking_sync:
            for collection in self:
                chunkset = collection._get_default_chunkset()
                if not chunkset:
                    continue
                splitter_values = {
                    "splitter_type": collection.default_splitter_type,
                    "chunk_size": collection.default_chunk_size,
                    "chunk_overlap": collection.default_chunk_overlap,
                    "context_model_id": False,
                }
                splitter = chunkset.splitter_id
                if len(splitter.chunkset_ids) > 1:
                    splitter = splitter.copy(
                        default=dict(
                            splitter_values,
                            name=_('%s Default Splitter', collection.name),
                        )
                    )
                    chunkset.write({"splitter_id": splitter.id})
                else:
                    splitter.write(splitter_values)
                chunkset.write({"state": "draft"})
                chunkset.vector_ids.write({"state": "draft"})
                collection._reset_ready_documents(
                    success_message=_(
                        "Default chunking method changed. Reset {count} "
                        "documents for rebuilding."
                    )
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
        """Drop each configured provider scope once and queue its documents to rebuild."""
        for collection in self:
            if not collection.database_ids:
                collection._post_styled_message(
                    _("No store databases are configured for this collection."),
                    message_type="info",
                )
                continue

            for database in collection.database_ids:
                database.action_drop()

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
        """Build every configured logical vector database for this collection."""
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
