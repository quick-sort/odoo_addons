import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class DiscussAgent(models.Model):
    """Polymorphic responder: *who* turns a Discuss message into a reply.

    ``discuss.agent`` is the interface record that binds a concrete responder
    (``llm.agent`` for an in-process LLM, ``agenthub.agent`` for an external
    JSON-RPC runtime such as agent-box) to the Discuss concerns that are common
    to both: the reply persona, the trigger policy, and the reply execution
    contract.

    The polymorphic reference is ``res_model`` + ``res_id``. This module never
    imports a concrete responder: the target is resolved at runtime and
    dispatched through the ``_discuss_execute`` protocol method that each bridge
    addon implements on its own model.
    """

    _name = "discuss.agent"
    _description = "Discuss Agent"
    _order = "name"

    name = fields.Char(required=True, translate=True)
    active = fields.Boolean(default=True)

    # Polymorphic reference to the concrete responder.
    agent_type = fields.Selection(
        selection=[],
        required=True,
        help="Concrete responder kind. Each bridge addon contributes one value "
        "via selection_add (e.g. 'llm' through discuss_agent_llm, 'agentbox' "
        "through discuss_agent_agenthub).",
    )
    res_model = fields.Char(
        required=True,
        help="Technical name of the model that implements _discuss_execute.",
    )
    res_id = fields.Integer(
        required=True,
        help="Record id of the concrete responder.",
    )

    # Discuss concerns shared by every responder, independent of its kind.
    discuss_user_id = fields.Many2one(
        "res.users",
        string="Reply Persona",
        ondelete="set null",
        help="Internal user whose partner authors the reply bubble in Discuss. "
        "Independent from the execution identity that runs the agent.",
    )
    discuss_enabled = fields.Boolean(
        string="Enable in Discuss",
        help="When enabled, messages in channels where the reply persona is a "
        "member may trigger a reply.",
    )
    discuss_trigger_mode = fields.Selection(
        [
            ("both", "Direct chat or @mention"),
            ("direct_chat", "Only in direct 1:1 chat"),
            ("mention", "Only when @mentioned"),
        ],
        string="Reply Trigger",
        default="both",
        required=True,
    )

    @api.constrains("res_model", "res_id")
    def _check_polymorphic_target(self):
        for agent in self:
            if not agent.res_model:
                raise ValidationError(
                    _("Agent '%s' has no responder model.") % agent.name
                )
            if agent.res_id <= 0:
                raise ValidationError(
                    _("Agent '%s' has no responder record.") % agent.name
                )

    def _discuss_resolve(self):
        """Return the concrete responder record (e.g. llm.agent / agenthub.agent)."""
        self.ensure_one()
        if self.res_model not in self.env:
            raise UserError(
                _("Unknown responder model '%s' for agent '%s'.")
                % (self.res_model, self.name)
            )
        target = self.env[self.res_model].browse(self.res_id).exists()
        if not target:
            raise UserError(
                _("The responder record for agent '%s' no longer exists.")
                % self.name
            )
        return target

    def _discuss_execute(
        self,
        *,
        execution_user,
        company,
        query,
        background=None,
        stream=False,
    ):
        """Generate a reply for ``query`` under ``execution_user``.

        Dispatches to the concrete responder's ``_discuss_execute`` protocol
        method. Contract (see docs/design.md):

        * synchronous form returns ``{"result_html"/"result"/"thread_id"}``
          or ``{"error": ...}``;
        * asynchronous form (external JSON-RPC agent) returns
          ``{"pending": True}`` and the reply arrives later through the
          ``discuss.reply.job`` completion entry point.
        """
        self.ensure_one()
        target = self._discuss_resolve()
        execute = getattr(target, "_discuss_execute", None)
        if execute is None:
            raise UserError(
                _("Responder model '%s' does not implement _discuss_execute.")
                % self.res_model
            )
        return execute(
            execution_user=execution_user,
            company=company,
            query=query,
            background=background,
            stream=stream,
        )

    def _discuss_enqueue_reply(self, channel, message, source_user, reply_partner):
        """Idempotently register one pending reply job, keeping persona and
        execution identity separate. Never blocks message posting."""
        self.ensure_one()
        if not reply_partner:
            return False

        Job = self.env["discuss.reply.job"].sudo()
        if Job.search(
            [("agent_id", "=", self.id), ("message_id", "=", message.id)],
            limit=1,
        ):
            return False
        Job.create(
            {
                "agent_id": self.id,
                "channel_id": channel.id,
                "message_id": message.id,
                "reply_partner_id": reply_partner.id,
                "source_user_id": source_user.id,
                "source_company_id": self.env.company.id,
            }
        )
        return True

    def _discuss_after_enqueue(self):
        """Hook for bridge addons to wake their consumer after a job is queued.

        The core does not know which worker consumes the job; each bridge
        addon overrides this to trigger its own cron / runtime.
        """
        pass

    @api.model
    def _discuss_dispatch(self, channel, message, msg_vals):
        """Evaluate trigger policy for every enabled agent and enqueue replies
        without blocking the user's message post."""
        source_user = self.env.user
        agents = self.sudo().search(
            [
                ("active", "=", True),
                ("discuss_enabled", "=", True),
                ("discuss_user_id", "!=", False),
            ]
        )
        if not agents:
            return

        for agent in agents:
            try:
                if not channel._discuss_user_can_use_agent(agent, source_user):
                    continue
                if not channel._discuss_should_trigger(agent, message, msg_vals):
                    continue
                if agent._discuss_enqueue_reply(
                    channel,
                    message,
                    source_user,
                    agent.discuss_user_id.partner_id,
                ):
                    agent._discuss_after_enqueue()
            except Exception:  # noqa: BLE001 - agent failure must not abort posting
                _logger.exception(
                    "discuss_agent: error dispatching agent %s on channel %s",
                    agent.id,
                    channel.id,
                )
