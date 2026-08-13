# Copyright 2026 Rui
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

"""Context-builder components.

Additive pipeline: every component in the ``agent.agent`` collection with
``_usage = "agent.context.builder"`` is collected and its ``build`` output is
concatenated into the ``prepend_messages`` sent to the provider. This is where
system prompts, tool hints, RAG context (in ``agent_knowledge``) and memory
compression plug in — without modifying the runner.

Order is controlled by ``_priority`` (lower first).
"""

import logging

from odoo.addons.component.core import AbstractComponent, Component

_logger = logging.getLogger(__name__)


class AgentContextBuilder(AbstractComponent):
    _name = "agent.context.builder"
    _collection = "agent.agent"
    _usage = "agent.context.builder"
    _priority = 100

    def build(self, agent, session, incoming=None):
        """Return a list of prepend messages ``[{"role", "content"}, ...]``.

        ``incoming`` is the ``mail.message`` record that triggered the turn.
        """
        raise NotImplementedError


class SystemPromptBuilder(Component):
    _name = "agent.context.builder.system"
    _inherit = "agent.context.builder"
    _priority = 10

    def build(self, agent, session, incoming=None):
        if not agent.system_prompt:
            return []
        rendered = self._render(agent.system_prompt, session)
        return [{"role": "system", "content": rendered}] if rendered else []

    def _render(self, template, session):
        """Render the system prompt as a Jinja template over thread context."""
        context = self._sanitize_context(session.get_context())
        try:
            from jinja2.sandbox import SandboxedEnvironment

            return SandboxedEnvironment().from_string(template).render(**context)
        except Exception:  # noqa: BLE001
            _logger.exception("Failed to render agent system prompt; using raw text")
            return template

    def _sanitize_context(self, context):
        """Flatten recordsets/proxies into plain values for safe rendering."""
        context = dict(context or {})
        proxy = context.get("related_record")
        if proxy is not None:
            try:
                record = getattr(proxy, "_record", None)
                context["related_record"] = (
                    {
                        "model": record._name,
                        "id": record.id,
                        "display_name": record.display_name,
                    }
                    if record
                    else None
                )
            except Exception:  # noqa: BLE001
                context["related_record"] = None
        return context


class ToolsBuilder(Component):
    _name = "agent.context.builder.tools"
    _inherit = "agent.context.builder"
    _priority = 20

    def build(self, agent, session, incoming=None):
        if not agent.tool_ids:
            return []
        lines = ["Available tools:"]
        for tool in agent.tool_ids:
            lines.append(f"- {tool.name}: {tool.description}")
        return [{"role": "system", "content": "\n".join(lines)}]
