# Copyright 2026 Rui
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

"""Wire ``llm.thread`` to an agent.

The thread keeps doing what ``llm_thread`` already does (advisory lock, role
subtypes, streaming message posts, store integration). We only attach an
``agent_id`` and override ``generate_messages`` to delegate to the agent's
runner component.
"""

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class LLMThread(models.Model):
    _inherit = "llm.thread"

    agent_id = fields.Many2one(
        "agent.agent", string="Agent", ondelete="restrict",
    )

    @api.onchange("agent_id")
    def _onchange_agent_id(self):
        if self.agent_id:
            self.provider_id = self.agent_id.provider_id
            self.model_id = self.agent_id.model_id
            self.tool_ids = self.agent_id.tool_ids

    def set_agent(self, agent_id):
        """Assign an agent to this thread and sync its related fields."""
        self.ensure_one()
        if not agent_id:
            return self.write({"agent_id": False})

        agent = self.env["agent.agent"].browse(agent_id)
        if not agent.exists():
            return False

        vals = {
            "agent_id": agent_id,
            "tool_ids": [(6, 0, agent.tool_ids.ids)],
        }
        if agent.provider_id:
            vals["provider_id"] = agent.provider_id.id
        if agent.model_id:
            vals["model_id"] = agent.model_id.id
        return self.write(vals)

    def generate_messages(self, last_message):
        """Delegate the generation loop to the agent's runner component."""
        self.ensure_one()
        agent = self.agent_id
        if not agent:
            raise UserError(_("This thread has no agent assigned."))

        if not last_message:
            last_message = self.env["mail.message"].search(
                [
                    ("model", "=", self._name),
                    ("res_id", "=", self.id),
                    ("llm_role", "!=", False),
                ],
                order="create_date DESC, id DESC",
                limit=1,
            )
            if not last_message:
                raise UserError(_("No message to respond to."))

        runner = agent._get_runner()
        result = yield from runner.run(agent, self, last_message)
        return result

    def _get_llm_history(self, limit=25):
        """Return recent LLM messages (chronological) for the context window.

        Error messages (``is_error=True``) are excluded, mirroring
        ``llm_thread``/``llm_assistant`` semantics.
        """
        self.ensure_one()
        domain = [
            ("model", "=", self._name),
            ("res_id", "=", self.id),
            ("llm_role", "!=", False),
            ("is_error", "=", False),
        ]
        recent = self.env["mail.message"].search(
            domain, order="create_date DESC, id DESC", limit=limit,
        )
        return recent.sorted(lambda m: (m.create_date, m.id))
