from odoo import fields, models

from odoo.addons.llm_knowledge.models.llm_resource_extractor import (
    archive_dangling_extractor,
)


class LLMResourceExtractor(models.Model):
    _inherit = "llm.resource.extractor"

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
