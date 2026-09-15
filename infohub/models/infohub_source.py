from odoo import fields, models


class InfohubSource(models.Model):
    """A content source — the publisher itself.

    A *source* is who the news belongs to (e.g. "Nature", "Reuters"), while an
    ``infohub.channel`` is *how* we obtain it. The two are orthogonal: the same
    source may be reachable both through its RSS feed and through a newsletter
    subscription, and those are two channels pointing at one source.
    """

    _name = "infohub.source"
    _description = "InfoHub Source"
    _order = "name"

    name = fields.Char(required=True)
    url = fields.Char(
        help="Homepage of the source, e.g. https://www.nature.com",
    )
    description = fields.Text(
        help="Free-form notes used to recognise this source in incoming items, "
        "such as its domain or the sender address of its newsletter "
        "(e.g. nature.com / newsletters@nature.com).",
    )
    active = fields.Boolean(default=True)

    item_ids = fields.One2many("infohub.item", "source_id", string="Items")
    item_count = fields.Integer(compute="_compute_item_count")

    def _compute_item_count(self):
        for source in self:
            source.item_count = len(source.item_ids)

    def action_open_items(self):
        """Open the items attributed to this source."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": "Items",
            "res_model": "infohub.item",
            "view_mode": "list,form",
            "domain": [("source_id", "=", self.id)],
            "context": {"default_source_id": self.id},
        }
