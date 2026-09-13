from odoo import _, api, fields, models
from odoo.exceptions import UserError

DEFAULT_CHUNK_SIZE = 200
DEFAULT_CHUNK_OVERLAP = 20


class LLMKnowledgeChunker(models.Model):
    """Continue processed documents through chunking and embedding."""

    _inherit = "llm.document"

    state = fields.Selection(
        selection_add=[("chunked", "Chunked"), ("ready", "Ready")],
        ondelete={"chunked": "cascade", "ready": "cascade"},
    )
    chunk_ids = fields.One2many(
        "llm.store.chunk",
        "document_id",
        string="Chunks",
        help="Chunk pointers created by this document's collection chunksets.",
    )
    chunk_count = fields.Integer(compute="_compute_chunk_count")

    @api.depends("chunk_ids")
    def _compute_chunk_count(self):
        for document in self:
            document.chunk_count = len(document.chunk_ids)

    def action_view_chunks(self):
        self.ensure_one()
        return {
            "name": _("Document Chunks"),
            "view_mode": "list,form",
            "res_model": "llm.store.chunk",
            "domain": [("document_id", "=", self.id)],
            "type": "ir.actions.act_window",
            "context": {"default_document_id": self.id},
        }

    def process_document(self, force_refresh=False):
        result = super().process_document(force_refresh=force_refresh)
        inconsistent = self.filtered(
            lambda document: document.state in ("chunked", "ready")
            and not document.chunk_ids
        )
        if inconsistent:
            inconsistent.write({"state": "processed"})
        processed = self.filtered(lambda document: document.state == "processed")
        if processed:
            processed.chunk()
        chunked = self.filtered(lambda document: document.state == "chunked")
        if chunked:
            chunked.embed()
        return result

    def chunk(self):
        documents = self.filtered(lambda document: document.state == "processed")
        locked = documents._lock() if documents else documents
        if not locked:
            return False
        try:
            locked.write({"state": "chunked"})
            locked._post_styled_message(
                _("Ready for embedding; splitting runs per database build."),
                "success",
            )
            return True
        except Exception as error:
            raise UserError(_("Error in batch chunking: %s", str(error))) from error
        finally:
            locked._unlock()

    def action_embed(self):
        if self.embed():
            self._post_styled_message(
                _("Document embedding process completed successfully."), "success"
            )
            return True
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Embedding"),
                "message": _("No documents were embedded. Check collection vectors."),
                "type": "warning",
                "sticky": False,
            },
        }

    def _invalidate_indexed_content(self):
        """Remove old chunk pointers and vectors before source reprocessing."""
        chunks = self.mapped("chunk_ids")
        if chunks:
            chunks.unlink()
        return True

    def unlink(self):
        """Clean provider records before document/chunk database cascades."""
        self._invalidate_indexed_content()
        return super().unlink()

    def action_force_refresh(self):
        self._invalidate_indexed_content()
        return super().action_force_refresh()

    def action_mass_reset(self):
        documents = self.browse(self.env.context.get("active_ids", []))
        documents._invalidate_indexed_content()
        return super().action_mass_reset()

    def action_reindex(self):
        self.ensure_one()
        collection = self.collection_id
        if not collection:
            return False
        chunks = self.chunk_ids
        if not chunks:
            return False
        self.write({"state": "chunked"})
        for vector in collection.vector_ids.filtered("store_id"):
            vector.delete_vectors(ids=chunks.ids)
        return True

    def action_mass_reindex(self):
        collections = self.mapped("collection_id")
        for collection in collections:
            collection.reindex_collection()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Reindexing"),
                "message": _(
                    "Reindexing requested for %(count)s collections.",
                    count=len(collections),
                ),
                "type": "success",
                "sticky": False,
            },
        }

    def embed(self):
        chunked = self.filtered(lambda document: document.state == "chunked")
        if not chunked:
            return False
        any_embedded = False
        for collection in chunked.mapped("collection_id"):
            documents = chunked.filtered(
                lambda document, owner=collection: document.collection_id == owner
            )
            result = collection.embed_documents(specific_document_ids=documents.ids)
            if result and result.get("success") and result.get("processed_documents"):
                any_embedded = True
        if not any_embedded:
            self._post_styled_message(
                _("No documents could be embedded. Check collection vector settings."),
                "warning",
            )
        return any_embedded

    def _reset_state_if_needed(self):
        self.ensure_one()
        if self.state == "ready":
            self.write({"state": "chunked"})
        return super()._reset_state_if_needed()
