from odoo import fields, models


class AgenthubBinding(models.Model):
    """Per-user routing: which agent answers on a given channel."""

    _name = "agenthub.binding"
    _description = "Agent Hub User Binding"
    _order = "user_id, channel_id"

    user_id = fields.Many2one(
        "res.users", required=True, ondelete="cascade", index=True
    )
    channel_id = fields.Many2one(
        "agenthub.channel", required=True, ondelete="cascade", index=True
    )
    agent_id = fields.Many2one(
        "agenthub.agent", required=True, ondelete="cascade", index=True
    )
    active = fields.Boolean(default=True)

    _binding_uniq = models.Constraint(
        "UNIQUE(user_id, channel_id)",
        "This user already has an agent on this channel.",
    )
