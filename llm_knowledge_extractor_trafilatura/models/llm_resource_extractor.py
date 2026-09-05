from odoo import fields, models

from odoo.addons.llm_knowledge.models.llm_resource_extractor import (
    archive_dangling_extractor,
)


class LLMResourceExtractor(models.Model):
    _inherit = "llm.resource.extractor"

    extractor_type = fields.Selection(
        selection_add=[("trafilatura", "Trafilatura")],
        ondelete={"trafilatura": archive_dangling_extractor},
    )
