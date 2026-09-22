from odoo import fields, models


class AgenthubChannel(models.Model):
    """WeCom aibot transport configuration for ``agenthub.channel``."""

    _inherit = "agenthub.channel"

    channel_type = fields.Selection(
        selection_add=[("wecom", "企业微信")],
        ondelete={"wecom": "cascade"},
    )

    bot_id = fields.Char(
        string="Bot ID",
        help="WeCom bot id, used by the subscribe handshake.",
    )
    secret = fields.Char(
        string="Secret",
        help="WeCom bot secret, validated on subscribe.",
    )
