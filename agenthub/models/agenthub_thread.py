import urllib.parse

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class AgenthubThread(models.Model):
    """A conversation — the runtime binding of a channel peer to an agent.

    Inherits ``mail.thread`` so messages are standard ``mail.message`` records
    and the conversation renders in the Discuss UI. ``channel_id`` says how the
    peer is reached, ``peer_ref`` says who the peer is, and ``agent_id`` says who
    answers. Threads are isolated per channel; the same user talking over
    Discuss and WeCom has two separate contexts.
    """

    _name = "agenthub.thread"
    _description = "Agent Hub Conversation"
    _inherit = ["mail.thread"]
    _order = "write_date DESC"

    name = fields.Char(string="Title", required=True)
    channel_id = fields.Many2one(
        "agenthub.channel",
        string="Channel",
        ondelete="restrict",
        help="External transport; Discuss-only threads leave it empty.",
    )
    peer_ref = fields.Char(
        string="Peer",
        required=True,
        help="Channel-side peer identifier (e.g. the WeCom userid).",
    )
    agent_id = fields.Many2one(
        "agenthub.agent", string="Agent", required=True, ondelete="restrict"
    )
    external_id = fields.Char(
        string="External ID",
        help="Stable channel-side conversation identifier, for idempotency.",
    )
    relay_thread_key = fields.Char(
        string="Relay Thread Key",
        index=True,
        copy=False,
        help="Stable key used by the relay; external channels get a deterministic value.",
    )
    discuss_channel_id = fields.Many2one(
        "discuss.channel",
        string="Discuss Channel",
        ondelete="set null",
        help="Linked discuss.channel when the conversation happens in Discuss.",
    )
    state = fields.Selection(
        [("active", "Active"), ("closed", "Closed")],
        default="active",
        required=True,
    )

    _thread_uniq = models.Constraint(
        "UNIQUE(channel_id, peer_ref, agent_id)",
        "A conversation for this peer and agent already exists on this channel.",
    )
    _relay_thread_key_uniq = models.Constraint(
        "UNIQUE(relay_thread_key)",
        "Relay thread key must be unique.",
    )

    @api.constrains("channel_id", "discuss_channel_id")
    def _check_transport(self):
        for thread in self:
            if not thread.channel_id and not thread.discuss_channel_id:
                raise ValidationError(
                    _("A thread needs either channel_id or discuss_channel_id.")
                )

    @api.model
    def _default_relay_thread_key(
        self, channel_id, peer_ref, agent_id, discuss_channel_id=None
    ):
        if discuss_channel_id:
            return f"discuss.channel:{discuss_channel_id}"
        if channel_id is None:
            raise ValueError(
                "channel_id or discuss_channel_id is required for relay_thread_key"
            )
        peer = urllib.parse.quote(str(peer_ref), safe="")
        return f"agenthub:channel:{channel_id}:peer:{peer}:agent:{agent_id}"

    @api.model
    def _find_or_create(
        self,
        channel_id,
        peer_ref,
        agent_id,
        name=None,
        relay_thread_key=None,
        discuss_channel_id=None,
    ):
        """Return the thread for ``(channel, peer, agent)``, creating it."""
        thread = self.search(
            [
                ("channel_id", "=", channel_id),
                ("peer_ref", "=", peer_ref),
                ("agent_id", "=", agent_id),
            ],
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
                "relay_thread_key": relay_thread_key
                or self._default_relay_thread_key(
                    channel_id, peer_ref, agent_id, discuss_channel_id
                ),
                "discuss_channel_id": discuss_channel_id or False,
            }
        )
