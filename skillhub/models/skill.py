import re

from odoo import api, fields, models
from odoo.exceptions import ValidationError

CODE_SLUG_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]*$")


class Skill(models.Model):
    _name = "skillhub.skill"
    _description = "Skill Package"
    _order = "code"

    code = fields.Char(required=True)
    title = fields.Char(required=True)
    description = fields.Text()
    version = fields.Char()
    state = fields.Selection(
        [("active", "Active"), ("archived", "Archived")],
        default="active",
        required=True,
    )
    is_public = fields.Boolean()
    shared_user_ids = fields.Many2many("res.users", string="Shared With")
    backend_id = fields.Many2one("storage.backend", required=True)
    storage_path = fields.Char(required=True)
    size = fields.Integer()
    sha256 = fields.Char()

    _unique_code = models.Constraint(
        "UNIQUE(code)",
        "A skill with this code already exists.",
    )

    @api.constrains("code")
    def _check_code_slug(self):
        for record in self:
            if not CODE_SLUG_RE.fullmatch(record.code or ""):
                raise ValidationError(
                    "Skill code must be a slug: letters, digits, '.', '_' or "
                    "'-', starting with a letter or digit."
                )
