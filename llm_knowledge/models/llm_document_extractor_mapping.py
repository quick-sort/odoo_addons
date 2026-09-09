from odoo import api, fields, models
from odoo.exceptions import ValidationError


class LLMDocumentExtractorMapping(models.Model):
    _name = "llm.document.extractor.mapping"
    _description = "LLM Document Extractor Mapping"
    _order = "sequence, id"

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    active = fields.Boolean(default=True)
    collection_id = fields.Many2one(
        "llm.knowledge.collection",
        string="Collection",
        ondelete="cascade",
        index=True,
        help="Leave empty for a global fallback mapping.",
    )
    mimetype = fields.Char(
        string="MIME Type",
        help="Exact MIME (application/pdf) or wildcard (text/*).",
    )
    extension = fields.Char(
        help="Exact filename extension, with or without a leading dot.",
    )
    extractor_id = fields.Many2one(
        "llm.document.extractor",
        required=True,
        ondelete="cascade",
        domain="[('active', '=', True)]",
    )

    @api.constrains("mimetype")
    def _check_mimetype_pattern(self):
        for mapping in self:
            mimetype = (mapping.mimetype or "").strip()
            if "*" in mimetype and not mimetype.endswith("/*"):
                raise ValidationError(
                    self.env._("MIME wildcards must use the form 'type/*'.")
                )
