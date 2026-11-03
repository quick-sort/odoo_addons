import hashlib
import hmac
import secrets

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

from odoo.addons.component.exception import NoComponentError, RegistryNotReadyError


class AgenthubAgent(models.Model):
    """A conversation partner — *who* turns an inbound message into a reply.

    Agents are a ``component`` collection. An agent is either an external
    agent-box instance reached through the relay (``runtime=relay``) or an
    in-process adapter (``runtime=in_process``).

    Every agent carries an execution identity. ``user_id`` is a dedicated
    service user; its partner is the conversation object users select in
    Discuss. ``owner_user_id`` records who authorised the agent and caps its
    permissions.
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
    runtime = fields.Selection(
        [("relay", "Relay"), ("in_process", "In Process")],
        default="in_process",
        required=True,
        help="External agent-box over the relay, or an in-process adapter. "
        "Existing legacy agents default to in_process; new external agents "
        "should select relay.",
    )
    active = fields.Boolean(default=True)

    user_id = fields.Many2one(
        "res.users",
        string="Execution User",
        required=True,
        ondelete="restrict",
        default=lambda self: self.env.user.id,
        help="Service user the agent acts as; its partner is shown in Discuss.",
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
    token_hash = fields.Char(
        string="Relay Token Hash",
        copy=False,
        help="Hash of the token the external agent presents to the relay.",
    )
    api_key = fields.Char(
        string="API Key",
        help="Legacy credential; new relay agents use token_hash.",
    )
    state = fields.Selection(
        [("offline", "Offline"), ("online", "Online"), ("busy", "Busy")],
        default="offline",
        readonly=True,
        help="Presence synced from the relay; display only.",
    )
    last_seen = fields.Datetime(readonly=True)
    workspace = fields.Json(
        help="Agent-box workspace/project metadata (informational).",
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

    @api.constrains("user_id", "active")
    def _check_unique_service_user(self):
        for agent in self:
            if not agent.active:
                continue
            duplicate = self.search_count(
                [
                    ("user_id", "=", agent.user_id.id),
                    ("active", "=", True),
                    ("id", "!=", agent.id),
                ]
            )
            if duplicate:
                raise ValidationError(
                    _(
                        "User '%s' is already the execution user of another active agent.",
                        agent.user_id.display_name,
                    )
                )

    def _agent_env(self):
        """Return the environment bound to this agent's execution user.

        Forces ``su=False`` so the agent never runs in superuser mode even when
        the caller is sudoed.
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
        if self.runtime == "relay":
            raise UserError(
                _(
                    "Agent '%s' is handled by the relay; dispatch happens through "
                    "the relay inbox, not reply()."
                )
                % self.name
            )
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

    def _generate_token(self):
        """Generate a relay token, store its hash, and return the plaintext."""
        self.ensure_one()
        token = secrets.token_urlsafe(32)
        self.write({"token_hash": self._hash_token(token)})
        return token

    @api.model
    def _hash_token(self, token):
        return hashlib.sha256(token.encode()).hexdigest()

    def _check_token(self, token):
        self.ensure_one()
        if not self.token_hash or not token:
            return False
        return hmac.compare_digest(self.token_hash, self._hash_token(token))
