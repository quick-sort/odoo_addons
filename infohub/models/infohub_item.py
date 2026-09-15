from odoo import api, fields, models
from odoo.tools import html2plaintext


class InfohubItem(models.Model):
    """A news item — the single pool every channel feeds into.

    ``channel_id`` records *how* the item arrived, ``source_id`` records *whose*
    it is. The same article reaching us through both an RSS feed and a
    newsletter produces two rows that differ only by channel.
    """

    _name = "infohub.item"
    _description = "InfoHub Item"
    _order = "published_at desc, id desc"

    channel_id = fields.Many2one(
        "infohub.channel", required=True, ondelete="cascade", index=True
    )
    source_id = fields.Many2one(
        "infohub.source",
        ondelete="set null",
        index=True,
        help="Who the item belongs to. Left empty when no known source matched.",
    )

    title = fields.Char(required=True)
    url = fields.Char()
    published_at = fields.Datetime(index=True)
    content = fields.Html(sanitize=True)
    content_text = fields.Text(help="Plain-text copy of the content, for searching.")

    channel_type = fields.Selection(related="channel_id.channel_type", store=True)

    external_id = fields.Char(
        index=True,
        help="Identity of the item within its channel, used for deduplication.",
    )
    raw_data = fields.Json(help="Original payload, kept so parsing can be re-run.")
    state = fields.Selection(
        [("new", "New"), ("accepted", "Accepted"), ("rejected", "Rejected")],
        default="new",
        required=True,
        index=True,
    )
    error_message = fields.Text()

    _item_unique = models.Constraint(
        "UNIQUE(channel_id, external_id)",
        "An item with this identity already exists in this channel.",
    )
    _timeline_idx = models.Index("(published_at DESC, id DESC)")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get("content_text"):
                html = vals.get("content")
                if html:
                    vals["content_text"] = html2plaintext(html)
        return super().create(vals_list)

    def name_get(self):
        return [(item.id, item.title or "") for item in self]

    def action_open_url(self):
        """Open the original article in a new tab."""
        self.ensure_one()
        if not self.url:
            return False
        return {
            "type": "ir.actions.act_url",
            "url": self.url,
            "target": "new",
        }
