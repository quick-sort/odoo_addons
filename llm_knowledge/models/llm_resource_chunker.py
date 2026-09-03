import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

# Kept for backward compatibility with existing data/migrations; no longer
# used to size actual chunks (chunk size now lives on
# llm.knowledge.splitter, one per llm.knowledge.chunkset).
DEFAULT_CHUNK_SIZE = 200
DEFAULT_CHUNK_OVERLAP = 20


class LLMKnowledgeChunker(models.Model):
    """Legacy per-resource chunking fields.

    Actual chunking is now owned by ``llm.knowledge.chunkset``/
    ``llm.knowledge.splitter`` (see llm_knowledge_chunkset.py,
    llm_knowledge_splitter.py): a chunkset splits a resource's markdown on
    demand, transiently, as part of building an
    ``llm.knowledge.vector``. There is no longer a persisted, resource-owned
    set of chunks with one fixed size -- chunk() below is now a pure state
    transition (parsed -> chunked) so process_resource()'s pipeline keeps
    working; it does not create any llm.knowledge.chunk rows itself.
    """

    _inherit = "llm.resource"

    chunk_ids = fields.One2many(
        "llm.knowledge.chunk",
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
            "res_model": "llm.knowledge.chunk",
            "domain": [("resource_id", "=", self.id)],
            "type": "ir.actions.act_window",
            "context": {"default_resource_id": self.id},
        }

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

