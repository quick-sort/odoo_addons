from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from odoo.addons.component.exception import NoComponentError, RegistryNotReadyError


class AgenthubAgent(models.Model):
    """A conversation partner — *who* turns an inbound message into a reply.

    Agents are a ``component`` collection. Each concrete agent type lives in its
    own addon (``agenthub_openclaw``, ...) and contributes a ``selection_add``
    entry on ``agent_type`` plus an ``agenthub.agent.adapter`` component resolved
    by usage.

    An agent is reached over whatever channel a ``agenthub.thread`` binds it to;
    the agent itself is channel-agnostic.

    Every agent carries an execution identity. ``user_id`` is a dedicated
    service user that the agent's tool calls and record reads/writes run as —
    never the owner and never ``sudo``. ``owner_user_id`` records who authorised
    the agent and caps its permissions. See ``docs/design.md`` →
    "执行身份与权限（agent 挂在用户上）".
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
        string="Execution User",
        required=True,
        ondelete="restrict",
        default=lambda self: self.env.user.id,
        help="User the agent acts as (tools, record reads/writes).",
    )
    owner_user_id = fields.Many2one(
        "res.users",
        string="Owner",
        ondelete="set null",
        default=lambda self: self.env.user.id,
        help="Who authorised this agent; the permission ceiling.",
    )
    partner_id = fields.Many2one(
        "res.partner",
        string="Display Partner",
        related="user_id.partner_id",
        readonly=True,
    )
    api_key = fields.Char(
        string="API Key",
        help="Credential the external agent presents to authenticate over JSON-RPC.",
    )

    @api.constrains("user_id", "owner_user_id")
    def _check_execution_user(self):
        for agent in self:
            if agent.user_id.share:
                raise ValidationError(
                    _("The execution user of agent '%s' must be an internal user.")
                    % agent.name
                )
            if not agent.user_id.active:
                raise ValidationError(
                    _("The execution user of agent '%s' must be active.") % agent.name
                )

    def _agent_env(self):
        """Return the environment bound to this agent's execution user.

        Forces ``su=False`` so the agent never runs in superuser mode even when
        the caller is sudoed — the same contract ``llm.agent._run_in_thread``
        relies on via ``with_user``.
        """
        self.ensure_one()
        return self.env(user=self.user_id, su=False)

    def _adapter(self):
        """Resolve the reply adapter for this agent's type, or ``None``."""
        self.ensure_one()
        try:
            with self.work_on(self._name) as work:
                return work.component(usage=self.agent_type)
        except (NoComponentError, RegistryNotReadyError):
            return None

    def reply(self, message):
        """Produce a reply for an inbound ``mail.message``, in the agent's env."""
        self.ensure_one()
        agent = self.with_env(self._agent_env())
        adapter = agent._adapter()
        if adapter is None:
            raise UserError(
                _(
                    "No agent adapter is registered for type '%(type)s'. "
                    "Is the addon providing it installed?",
                    type=agent.agent_type,
                )
            )
        return adapter.reply(agent, message)
