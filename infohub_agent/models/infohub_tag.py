from odoo import _, fields, models


class InfohubTag(models.Model):
    """A taxonomy entry the tagging agent may assign to news items.

    The set of tags is expected to be small and fairly stable: the m2m
    relation table carries a PRIMARY KEY(item_id, tag_id) plus an
    INDEX(tag_id, item_id), so both lookup directions are index scans and the
    index never grows beyond items x tags rows.

    Deleting a tag only detaches it from items (the m2m cascades); the list
    view shows ``item_count`` so the impact is visible beforehand.
    """

    _name = "infohub.tag"
    _description = "InfoHub Tag"
    _order = "sequence, id"

    name = fields.Char(required=True)
    code = fields.Char(
        required=True,
        index=True,
        help="Stable identifier the LLM emits in its answer, e.g. "
        "\"clinical\". Renaming it changes what the model matches on; "
        "prefer fixing the display name instead.",
    )
    description = fields.Text(
        help="When to apply this tag. Included verbatim in the tagging "
        "prompt, so write it for the model, not for humans.",
    )
    sequence = fields.Integer(default=10)
    color = fields.Integer()
    active = fields.Boolean(default=True)

    item_ids = fields.One2many("infohub.item", "tag_ids", string="Items")
    item_count = fields.Integer(compute="_compute_item_count")

    _code_uniq = models.Constraint(
        "UNIQUE(code)",
        "Tag code must be unique.",
    )

    def _compute_item_count(self):
        for tag in self:
            tag.item_count = len(tag.item_ids)

    def action_open_items(self):
        """Open the items carrying this tag."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Items"),
            "res_model": "infohub.item",
            "view_mode": "list,form",
            "domain": [("tag_ids", "=", self.id)],
        }
