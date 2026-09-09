from odoo import fields, models

from odoo.addons.llm_knowledge.models.llm_document_extractor import (
    archive_dangling_extractor,
)


class LLMDocumentExtractor(models.Model):
    _inherit = "llm.document.extractor"

    extractor_type = fields.Selection(
        selection_add=[("mineru", "MinerU")],
        ondelete={"mineru": archive_dangling_extractor},
    )
    api_url = fields.Char(
        string="API URL",
        help="Base URL of the MinerU extraction service.",
    )
    api_key = fields.Char(
        string="API Key",
        help="Credentials for the MinerU extraction service.",
    )
