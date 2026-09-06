from odoo import fields, models


class DatasetTag(models.Model):
    _name = "dataset.tag"
    _description = "Dataset Tag"

    name = fields.Char(required=True, index=True)
    color = fields.Integer(string="Color Index", default=0)

    _name_unique = models.Constraint("unique(name)", "Tag name must be unique!")
