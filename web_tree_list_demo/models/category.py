from odoo import fields, models


class Category(models.Model):
    _name = "web_tree_list_demo.category"
    _description = "Tree List Demo Category"
    _order = "sequence, name"

    name = fields.Char(required=True)
    sequence = fields.Integer(default=10)
    parent_id = fields.Many2one(
        "web_tree_list_demo.category", string="Parent", ondelete="cascade", index=True
    )
    child_ids = fields.One2many("web_tree_list_demo.category", "parent_id", string="Children")
    description = fields.Text()
