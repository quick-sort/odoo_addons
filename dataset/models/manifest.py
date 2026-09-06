from odoo import api, fields, models


class Manifest(models.Model):
    _name = "dataset.manifest"
    _description = "Manifest"
    _order = "id desc"

    name = fields.Char(required=True)
    description = fields.Text()
    type = fields.Selection([("dataset", "Dataset")], required=True, default="dataset")
    values = fields.Json(
        help="List of chunk metadata dictionaries declared by this manifest."
    )
    total_chunks = fields.Integer(
        string="Expected Chunks",
        compute="_compute_total_chunks",
        store=True,
        help="Expected number of chunks declared by this manifest.",
    )

    _name_unique = models.Constraint("unique(name)", "Manifest name must be unique!")

    @api.depends("values")
    def _compute_total_chunks(self):
        for record in self:
            record.total_chunks = len(record.values or [])
