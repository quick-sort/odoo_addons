from odoo import _, fields, models
from odoo.exceptions import UserError

from odoo.addons.component.exception import NoComponentError, RegistryNotReadyError


class AgenthubAgent(models.Model):
    """A conversation partner — *who* turns an inbound message into a reply.

    Agents are a ``component`` collection. Each concrete agent type lives in its
    own addon (``agenthub_openclaw``, ...) and contributes a ``selection_add``
    entry on ``agent_type`` plus an ``agenthub.agent.adapter`` component resolved
    by usage.

    An agent is reached over whatever channel a ``agenthub.thread`` binds it to;
    the agent itself is channel-agnostic.
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
