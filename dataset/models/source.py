from odoo import fields, models
from odoo.exceptions import ValidationError


class Source(models.Model):
    _name = "dataset.source"
    _description = "Dataset Source"
    _order = "id desc"

    name = fields.Char(required=True)
    code = fields.Char(required=True)
    url = fields.Char(string="URL")
    description = fields.Text()

    def write(self, vals):
        if "code" in vals and self.env["dataset"].search_count(
            [("source_id", "in", self.ids), ("chunk_ids", "!=", False)]
        ):
            raise ValidationError(
                "Source code cannot change while its datasets contain chunks."
            )
        return super().write(vals)

    _code_unique = models.Constraint("unique(code)", "Source code must be unique!")
    _name_unique = models.Constraint("unique(name)", "Source name must be unique!")
