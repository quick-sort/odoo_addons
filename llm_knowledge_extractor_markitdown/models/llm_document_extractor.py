from odoo import fields, models

from odoo.addons.llm_knowledge.models.llm_document_extractor import (
    archive_dangling_extractor,
)


class LLMDocumentExtractor(models.Model):
    _inherit = "llm.document.extractor"

    extractor_type = fields.Selection(
        selection_add=[("markitdown", "MarkItDown")],
        ondelete={"markitdown": archive_dangling_extractor},
    )
