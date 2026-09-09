import logging

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)


class LLMKnowledgeCollection(models.Model):
    """A knowledge base owning documents and their cached artifacts."""

    _name = "llm.knowledge.collection"
    _description = "Knowledge Collection for RAG"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "name"

    name = fields.Char(required=True, tracking=True)
    description = fields.Text(tracking=True)
    active = fields.Boolean(default=True, tracking=True)
    cache_backend_id = fields.Many2one(
        "storage.backend",
        string="Cache Backend",
        ondelete="restrict",
        tracking=True,
        help="Storage for downloaded URL binaries, extracted Markdown, and future "
        "processing artifacts. File documents continue to read their original bytes "
        "directly from the source backend.",
    )
    source_backend_id = fields.Many2one(
        "storage.backend",
        string="Source Backend",
        ondelete="restrict",
        tracking=True,
        help="Storage backend holding this collection's original files.",
    )
    source_path = fields.Char(
        string="Source Path",
        help="Optional subfolder inside the Source Backend to scan.",
    )
    document_ids = fields.One2many(
        "llm.document",
        "collection_id",
        string="Documents",
    )
    extractor_mapping_ids = fields.One2many(
        "llm.document.extractor.mapping",
        "collection_id",
        string="Extractor Mappings",
        help="Collection-specific file type mappings. Global mappings are used only "
        "when no collection mapping matches.",
    )
    document_count = fields.Integer(compute="_compute_document_count")

    @api.depends("document_ids")
    def _compute_document_count(self):
        for collection in self:
            collection.document_count = len(collection.document_ids)

    def action_view_documents(self):
        self.ensure_one()
        return {
            "name": _("Collection Documents"),
            "view_mode": "list,form",
            "res_model": "llm.document",
            "domain": [("collection_id", "=", self.id)],
            "type": "ir.actions.act_window",
            "context": {"default_collection_id": self.id},
        }

    def process_documents(self):
        """Process documents through retrieval and Markdown extraction."""
        for collection in self:
            collection.document_ids.process_document()
        return True

    def action_open_upload_wizard(self):
        self.ensure_one()
        return {
            "name": _("Upload Documents"),
            "type": "ir.actions.act_window",
            "res_model": "llm.upload.document.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_collection_id": self.id,
                "default_document_name_template": "{filename}",
            },
        }

    def _handle_removed_documents(self, removed_document_ids):
        """Extension point used by llm_store to remove vectors/chunks."""
        self.ensure_one()
        if removed_document_ids:
            _logger.info(
                "Documents %s were removed from collection %s",
                removed_document_ids,
                self.id,
            )
            documents = self.env["llm.document"].browse(removed_document_ids)
            for document in documents:
                document._reset_state_if_needed()
        return True
