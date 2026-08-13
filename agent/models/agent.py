# Copyright 2026 Rui
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

"""Declarative agent.

``agent.agent`` is the polymorphic host (a ``collection.base``) for the
components that make an agent behave: the runner (ReAct loop by default), the
context builders (system prompt, tools, future RAG...) and — indirectly — the
provider adapter and tool executors resolved through ``llm.provider`` and
``llm.tool`` collections.

Mirrors ``knowledge.extractor`` / ``knowledge.vector.store``: a ``*_type``
selection maps 1:1 onto a component ``usage`` in the matching collection.
"""

import logging

from odoo import api, fields, models
from odoo.modules.registry import Registry

_logger = logging.getLogger(__name__)


class Agent(models.Model):
    _name = "agent.agent"
    _description = "Agent"
    _inherit = ["collection.base"]

    name = fields.Char(required=True)
    code = fields.Char(
        string="Code",
        index=True,
        help="Unique code to invoke this agent headlessly (composable agents).",
    )
    active = fields.Boolean(default=True)

    provider_id = fields.Many2one(
        "llm.provider", required=True, ondelete="restrict",
    )
    model_id = fields.Many2one(
        "llm.model",
        domain="[('provider_id', '=', provider_id)]",
        ondelete="restrict",
    )

    system_prompt = fields.Text(
        string="System Prompt",
        help="Jinja template rendered with the thread context (see llm.thread.get_context).",
    )
    tool_ids = fields.Many2many("llm.tool", string="Tools")
    tool_calls_max = fields.Integer(
        string="Max Tool Calls", default=20,
        help="Maximum number of assistant→tool rounds before breaking the loop.",
    )
    context_limit = fields.Integer(
        string="Context Limit", default=25,
        help="Maximum number of recent messages sent as conversation history.",
    )

    temperature = fields.Float()
    max_tokens = fields.Integer()
    use_streaming = fields.Boolean(
        string="Streaming", default=False,
        help="Stream the assistant response chunk by chunk.",
    )

    runner = fields.Selection(
        selection=lambda self: self._selection_runner(),
        required=True,
        default="react",
    )

    thread_ids = fields.One2many("llm.thread", "agent_id", string="Threads")

    _sql_constraints = [
        ("code_unique", "UNIQUE(code)", "Agent code must be unique."),
    ]

    # ------------------------------------------------------------------
    # Component resolution (the polymorphic seam)
    # ------------------------------------------------------------------

    @api.model
    def _selection_runner(self):
        return [
            (usage, usage.replace("_", " ").title())
            for usage in self._get_available_runners()
        ]

    @api.model
    def _get_available_runners(self):
        """Usages of the runner components shipped with this addon.

        Concrete strategies (plan-execute, handoff...) register their usage in
        extending addons::

            return super()._get_available_runners() + ["plan_execute"]
        """
        return ["react"]

    def _get_runner(self):
        """Return the runner component for this agent's ``runner`` usage."""
        self.ensure_one()
        with self.work_on("llm.thread") as work:
            return work.component(usage=self.runner)

    def _get_context_builders(self):
        """Return the ordered context-builder components for this agent."""
        self.ensure_one()
        with self.work_on("llm.thread") as work:
            builders = work.many_components(usage="agent.context.builder")
        return sorted(builders, key=lambda b: getattr(b, "_priority", 100))

    def action_test(self):
        """Probe the provider/model connectivity and show a notification."""
        self.ensure_one()
        model = self.model_id or self.provider_id.get_model(model_use="chat")
        try:
            result = self.provider_id.test_model(model)
            state = result.get("state", "failed")
            message = result.get("message", "")
        except Exception as exc:  # noqa: BLE001
            state, message = "failed", str(exc)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": self.env._("Agent Test"),
                "message": message,
                "type": {"success": "success", "warning": "warning"}.get(
                    state, "danger"
                ),
                "sticky": False,
            },
        }

    # ------------------------------------------------------------------
    # Invocation (headless)
    # ------------------------------------------------------------------

    def invoke(self, query, thread_vals=None, new_cursor=True):
        """Run this agent on a fresh thread and return a result dict.

        ``query`` is sent as the first user message. The agent body never
        commits — it only flushes — so it composes with the caller's
        transaction policy:

        - ``new_cursor=True`` (default): open an isolated cursor, use this when
          called from inside another tool/agent (their savepoint must not be
          destroyed). Also increments a depth guard against runaway chains.
        - ``new_cursor=False``: run on the caller's cursor, for ``queue_job`` /
          cron entry points that own the transaction boundary.

        Returns ``{"query", "result", "error", "thread_id"}``.
        """
        self.ensure_one()
        if not new_cursor:
            return self._run_in_thread(query, thread_vals=thread_vals)

        context = {
            **self.env.context,
            "llm_invoke_agent_depth": self.env.context.get(
                "llm_invoke_agent_depth", 0
            ) + 1,
        }
        with Registry(self.env.cr.dbname).cursor() as cr:
            env = api.Environment(cr, self.env.uid, context)
            return self.with_env(env)._run_in_thread(query, thread_vals=thread_vals)

    def _run_in_thread(self, query, thread_vals=None):
        self.ensure_one()
        vals = {
            "provider_id": self.provider_id.id,
            "model_id": self.model_id.id,
        }
        if thread_vals:
            vals.update(thread_vals)

        thread = self.env["llm.thread"].create(vals)
        thread.set_agent(self.id)

        error = None
        try:
            for _event in thread.generate(user_message_body=query):
                pass
        except Exception as exc:  # noqa: BLE001
            _logger.exception("Error running agent '%s'", self.code or self.name)
            error = str(exc)

        self.env.flush_all()
        message = self.env["mail.message"].search(
            [("model", "=", "llm.thread"), ("res_id", "=", thread.id)],
            order="id desc",
            limit=1,
        )

        result = None
        if message:
            raw = (
                message.body_json.get("content")
                if isinstance(message.body_json, dict)
                else None
            )
            result = raw or (str(message.body) if message.body else None)

        return {
            "query": query,
            "result": result,
            "error": error,
            "thread_id": thread.id,
        }

    @api.model
    def invoke_agent(self, agent_code, query, thread_vals=None, new_cursor=True):
        """Look up an agent by code and run it (see ``invoke``)."""
        agent = self.search([("code", "=", agent_code)], limit=1)
        if not agent:
            return {
                "query": query,
                "result": None,
                "error": f"Agent with code '{agent_code}' not found.",
                "thread_id": None,
            }
        return agent.invoke(
            query, thread_vals=thread_vals, new_cursor=new_cursor,
        )
