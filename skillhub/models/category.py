from odoo import fields, models


class SkillCategory(models.Model):
    _name = "skillhub.category"
    _description = "Skill Category"
    _order = "name"

    name = fields.Char(required=True)

    _unique_name = models.Constraint(
        "UNIQUE(name)",
        "A category with this name already exists.",
    )
