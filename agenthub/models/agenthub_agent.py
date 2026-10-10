from odoo import _, fields, models
from odoo.exceptions import UserError

from odoo.addons.component.exception import NoComponentError, RegistryNotReadyError


class AgenthubAgent(models.Model):
    """A conversation partner — *who* turns an inbound message into a reply.

    Agents are a ``component`` collection. Each concrete agent type lives in its
    own addon (``agenthub_openclaw``, ...) and contributes a ``selection_add``
    entry on ``agent_type`` plus an ``agenthub.agent.adapter`` component resolved
    by usage.

    An agent owns the channels that reach it (``channel_ids``): each channel
    belongs to exactly one agent, while an agent may back several channels. An
    agent may also be owned by a user (``user_id``); one without an owner is a
    system agent shared across users.
    """

    _name = "agenthub.agent"
    _description = "Agent Hub Agent"
    _inherit = ["collection.base"]
    _order = "name"

    name = fields.Char(required=True)
    agent_type = fields.Selection(
        selection=[],
        required=True,
        help="Who the conversation partner is. Each agent addon adds its own value.",
    )
    active = fields.Boolean(default=True)
    user_id = fields.Many2one(
        "res.users",
        string="Owner",
        ondelete="set null",
        help="User who owns this agent. Empty means a system agent shared "
        "across users.",
    )
    channel_ids = fields.One2many(
        "agenthub.channel", "agent_id", string="Channels"
    )

    def _adapter(self):
        """Resolve the reply adapter for this agent's type, or ``None``."""
        self.ensure_one()
        try:
            with self.work_on(self._name) as work:
                return work.component(usage=self.agent_type)
        except (NoComponentError, RegistryNotReadyError):
            return None

    def reply(self, message):
        """Produce a reply for an inbound ``mail.message``."""
        self.ensure_one()
        adapter = self._adapter()
        if adapter is None:
            raise UserError(
                _(
                    "No agent adapter is registered for type '%(type)s'. "
                    "Is the addon providing it installed?",
                    type=self.agent_type,
                )
            )
        return adapter.reply(self, message)
