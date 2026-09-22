from odoo import api, fields, models


class AgenthubThread(models.Model):
    """A conversation — the runtime binding of a channel peer to an agent.

    Inherits ``mail.thread`` so messages are standard ``mail.message`` records
    and the conversation renders in the Discuss UI. ``channel_id`` says how the
    peer is reached, ``peer_ref`` says who the peer is, and ``agent_id`` says who
    answers. The binding is data, not code: channel and agent addons stay
    mutually independent.
    """

    _name = "agenthub.thread"
    _description = "Agent Hub Conversation"
    _inherit = ["mail.thread"]
    _order = "write_date DESC"

    name = fields.Char(string="Title", required=True)
    channel_id = fields.Many2one(
        "agenthub.channel", string="Channel", required=True, ondelete="restrict"
    )
    peer_ref = fields.Char(
        string="Peer",
        required=True,
        help="Channel-side peer identifier (e.g. the WeCom bot_id).",
    )
    agent_id = fields.Many2one(
        "agenthub.agent", string="Agent", required=True, ondelete="restrict"
    )
    external_id = fields.Char(
        string="External ID",
        help="Stable channel-side conversation identifier, for idempotency.",
    )
    state = fields.Selection(
        [("active", "Active"), ("closed", "Closed")],
        default="active",
        required=True,
    )

    _thread_uniq = models.Constraint(
        "UNIQUE(channel_id, peer_ref)",
        "A conversation for this peer already exists on this channel.",
    )

    @api.model
    def _find_or_create(self, channel_id, peer_ref, agent_id=None, name=None):
        """Return the thread for ``(channel, peer)``, creating it if needed."""
        thread = self.search(
            [("channel_id", "=", channel_id), ("peer_ref", "=", peer_ref)],
            limit=1,
        )
        if thread:
            return thread
        return self.create(
            {
                "name": name or peer_ref,
                "channel_id": channel_id,
                "peer_ref": peer_ref,
                "agent_id": agent_id,
            }
        )
