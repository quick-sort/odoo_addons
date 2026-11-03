from odoo import fields, models


class AgenthubIdentity(models.Model):
    """Map a channel-side peer to an Odoo user."""

    _name = "agenthub.identity"
    _description = "Agent Hub Channel Identity"
    _order = "channel_id, peer_ref"

    channel_id = fields.Many2one(
        "agenthub.channel", required=True, ondelete="cascade", index=True
    )
    peer_ref = fields.Char(required=True, index=True)
    user_id = fields.Many2one(
        "res.users", required=True, ondelete="cascade", index=True
    )
    partner_id = fields.Many2one(
        "res.partner", related="user_id.partner_id", store=True, readonly=True
    )
    active = fields.Boolean(default=True)

    _identity_uniq = models.Constraint(
        "UNIQUE(channel_id, peer_ref)",
        "This peer is already mapped on this channel.",
    )
