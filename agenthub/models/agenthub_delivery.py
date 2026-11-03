from odoo import fields, models


class AgenthubDelivery(models.Model):
    """Audit copy of a relay delivery; the hot queue lives in the relay."""

    _name = "agenthub.delivery"
    _description = "Agent Hub Delivery Audit"
    _order = "id desc"

    turn_id = fields.Many2one(
        "agenthub.turn", required=True, ondelete="cascade", index=True
    )
    message_id = fields.Many2one("mail.message", ondelete="set null", index=True)
    agent_id = fields.Many2one("agenthub.agent", ondelete="set null", index=True)
    channel_id = fields.Many2one(
        "agenthub.channel", ondelete="set null", index=True
    )
    leg = fields.Selection(
        [("to_agent", "To Agent"), ("to_user", "To User")],
        required=True,
        index=True,
    )
    relay_delivery_id = fields.Char(index=True)
    state = fields.Selection(
        [
            ("queued", "Queued"),
            ("claimed", "Claimed"),
            ("running", "Running"),
            ("done", "Done"),
            ("failed", "Failed"),
            ("dead", "Dead"),
        ],
        default="queued",
        required=True,
        index=True,
    )
    attempt = fields.Integer(default=0)
    error = fields.Text()
    sent_at = fields.Datetime()
