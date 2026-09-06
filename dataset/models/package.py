from odoo import fields, models


class Package(models.Model):
    _name = "dataset.package"
    _description = "Dataset Package"
    _order = "id desc"
    _parent_store = True

    name = fields.Char(required=True)
    code = fields.Char(required=True)
    description = fields.Text()
    parent_id = fields.Many2one("dataset.package", index=True)
    parent_path = fields.Char(index=True)
    child_ids = fields.One2many("dataset.package", "parent_id")

    _name_parent_unique = models.Constraint(
        "unique(name, parent_id)", "Package name must be unique within same parent!"
    )
    _code_parent_unique = models.Constraint(
        "unique(code, parent_id)", "Package code must be unique within same parent!"
    )
