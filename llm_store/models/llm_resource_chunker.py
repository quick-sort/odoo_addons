import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Kept for backward compatibility with existing data/migrations; sizing
# lives on llm.knowledge.splitter (one per llm.knowledge.chunkset) now.
DEFAULT_CHUNK_SIZE = 200
DEFAULT_CHUNK_OVERLAP = 20


class LLMKnowledgeChunker(models.Model):
    """Extends llm.resource (from llm_knowledge) with the chunking/
    embedding continuation of its pipeline.

    llm_knowledge's own state machine ends at 'parsed'. This addon adds
    'chunked' and 'ready' states: a chunkset splits a resource's markdown
    on demand, transiently, as part of building an llm.knowledge.vector --
    there is no persisted, resource-owned set of chunks with one fixed
    size. chunk() below is a pure state transition (parsed -> chunked); it
    does not create any llm.store.chunk rows itself.
    """

    _inherit = "llm.resource"

    state = fields.Selection(
        selection_add=[
            ("chunked", "Chunked"),
            ("ready", "Ready"),
        ],
        ondelete={"chunked": "cascade", "ready": "cascade"},
    )
    chunk_ids = fields.One2many(
        "llm.store.chunk",
        "resource_id",
        string="Chunks",
        help="Chunk pointers created across this resource's collections' "
        "chunksets. Populated once a vector configuration has been built "
        "for this resource, not on parse/chunk.",
    )
    chunk_count = fields.Integer(
        string="Chunk Count",
        compute="_compute_chunk_count",
    )

    @api.depends("chunk_ids")
    def _compute_chunk_count(self):
        for record in self:
            record.chunk_count = len(record.chunk_ids)

    def action_view_chunks(self):
        """Open a view with all chunks for this resource"""
        self.ensure_one()
        return {
            "name": _("Resource Chunks"),
            "view_mode": "list,form",
            "res_model": "llm.store.chunk",
            "domain": [("resource_id", "=", self.id)],
            "type": "ir.actions.act_window",
            "context": {"default_resource_id": self.id},
        }

    def process_resource(self):
        """Continue the base retrieve/parse pipeline into chunking and
        embedding once a resource reaches 'parsed'."""
        result = super().process_resource()

        # Process chunking and embedding
        inconsistent_docs = self.filtered(
            lambda d: d.state in ("chunked", "ready") and not d.chunk_ids
        )
        if inconsistent_docs:
            inconsistent_docs.write({"state": "parsed"})

        parsed_docs = self.filtered(lambda d: d.state == "parsed")
        if parsed_docs:
            parsed_docs.chunk()

        chunked_docs = self.filtered(lambda d: d.state == "chunked")
        if chunked_docs:
            chunked_docs.embed()

        return result

    def chunk(self):
        """Move parsed resources to 'chunked', gating them for embedding.
        No chunk rows are created here -- see module docstring."""
        resources = self.filtered(lambda r: r.state == "parsed")
        if not resources:
            return False

        locked = resources._lock()
        if not locked:
            return False

        try:
            locked.write({"state": "chunked"})
            for resource in locked:
                resource._post_styled_message(
                    "Ready for embedding (chunking happens per vector "
                    "configuration when building embeddings).",
                    "success",
                )
            locked._unlock()
            return True
        except Exception as e:
            locked._unlock()
            raise UserError(_("Error in batch chunking: %s") % str(e)) from e

    def action_embed(self):
        """Action handler for embedding document chunks"""
        result = self.embed()
        if result:
            self._post_styled_message(
                _("Document embedding process completed successfully."),
                "success",
            )
            return True
        else:
            message = _(
                "Document embedding process did not complete properly, check logs on resources."
            )
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Embedding"),
                    "message": message,
                    "type": "warning",
                    "sticky": False,
                },
            }

    def action_reindex(self):
        """Reindex a single resource's chunks"""
        self.ensure_one()

        collections = self.collection_ids
        if not collections:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Reindexing"),
                    "message": _("Resource does not belong to any collections."),
                    "type": "warning",
                },
            }

        chunks = self.chunk_ids
        if not chunks:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Reindexing"),
                    "message": _("No chunks found for this resource."),
                    "type": "warning",
                },
            }

        self.write({"state": "chunked"})

        for collection in collections:
            for vector in collection.vector_ids:
                if not vector.store_id:
                    continue
                try:
                    vector.delete_vectors(ids=chunks.ids)
                except Exception as e:
                    _logger.warning(
                        f"Error removing vectors for chunks from vector {vector.id}: {str(e)}"
                    )

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Reindexing"),
                "message": _(
                    f"Reset resource for re-embedding in {len(collections)} collections."
                ),
                "type": "success",
            },
        }

    def action_mass_reindex(self):
        """Reindex multiple resources at once"""
        collections = self.env["llm.knowledge.collection"]
        for resource in self:
            collections |= resource.collection_ids

        for collection in collections:
            collection.reindex_collection()

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Reindexing"),
                "message": _(
                    f"Reindexing request submitted for {len(collections)} collections."
                ),
                "type": "success",
                "sticky": False,
            },
        }

    def embed(self):
        """
        Embed resource chunks in collections by calling the collection's embed_resources method.
        Called after chunking to create vector representations.

        Returns:
            bool: True if any resources were successfully embedded, False otherwise
        """
        chunked_docs = self.filtered(lambda d: d.state == "chunked")

        if not chunked_docs:
            self._post_styled_message(
                _("No resources in 'chunked' state to embed."),
                "warning",
            )
            return False

        collections = self.env["llm.knowledge.collection"]
        for doc in chunked_docs:
            collections |= doc.collection_ids

        if not collections:
            self._post_styled_message(
                _("No collections found for the selected resources."),
                "warning",
            )
            return False

        any_embedded = False

        for collection in collections:
            result = collection.embed_resources(specific_resource_ids=chunked_docs.ids)
            if (
                result
                and result.get("success")
                and result.get("processed_resources", 0) > 0
            ):
                any_embedded = True

        if not any_embedded:
            self._post_styled_message(
                _(
                    "No resources could be embedded. Check that resources have correct collections and collections have valid embedding models and stores."
                ),
                "warning",
            )
        return any_embedded

    def _reset_state_if_needed(self):
        """Reset resource state to 'chunked' if it's in 'ready' state and
        not in any collection anymore."""
        self.ensure_one()
        if self.state == "ready" and not self.collection_ids:
            self.write({"state": "chunked"})
            _logger.info(
                f"Reset resource {self.id} to 'chunked' state after removal from all collections"
            )
            self._post_styled_message(
                _("Reset to 'chunked' state after removal from all collections"),
                "info",
            )
        return super()._reset_state_if_needed()
