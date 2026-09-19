"""The ``invoke_agent`` tool: delegate a sub-task to another agent.

An ``@llm_tool`` method on an abstract model, so the startup scan registers it
like any other code-owned tool. It needed a dedicated ``implementation``
selection value and an executor component before; now it needs neither.
"""

import logging
import time
from typing import Any

from odoo import models

from odoo.addons.llm.decorators import llm_tool

_logger = logging.getLogger(__name__)

# Maximum nesting depth for invoke_agent calls. Each invocation increments
# a context counter so an agent delegating to a chain of sub-agents
# cannot loop forever (e.g. A -> B -> A -> B ...).
DEFAULT_MAX_DEPTH = 5


def _preview(s: str, limit: int = 200) -> str:
    """Truncate a string for log output."""
    if s is None:
        return ""
    return s if len(s) <= limit else s[:limit] + f"...<+{len(s) - limit}c>"


class LLMToolInvokeAssistant(models.AbstractModel):
    _name = "llm.tool.invoke.agent"
    _description = "Agent delegation tool"

    @llm_tool(destructive_hint=False, open_world_hint=False)
    def invoke_agent(
        self,
        agent_code: str,
        query: str,
    ) -> dict[str, Any]:
        """
        Delegate a sub-task to another agent identified by its code.

        The sub-agent runs in an isolated transaction with its own thread,
        message stream, and tool execution lifecycle. Use this to compose
        specialized agents instead of replicating their tool sequences
        yourself.

        The returned dict carries the sub-agent's final answer in
        ``result`` (a string), or an ``error`` field if the invocation failed.

        Parameters:
            agent_code: Unique code of the sub-agent to invoke
                (e.g. "web_researcher", "statement_updater"). Use the value
                stored in llm.agent.code.
            query: Natural-language instruction or question to send to the
                sub-agent as the first user message.
        """
        depth = self.env.context.get("llm_invoke_agent_depth", 0)
        _logger.info(
            "[invoke_agent] ENTER depth=%d code=%r query_len=%d preview=%r",
            depth, agent_code, len(query or ""), _preview(query),
        )

        if depth >= DEFAULT_MAX_DEPTH:
            msg = (
                f"invoke_agent nesting depth limit reached "
                f"({DEFAULT_MAX_DEPTH}); refusing to call '{agent_code}'."
            )
            _logger.warning("[invoke_agent] BLOCKED depth=%d %s", depth, msg)
            return {"error": msg}

        start = time.monotonic()
        res = self.env["llm.agent"].invoke_agent(
            agent_code,
            query,
            parent_context={"llm_invoke_agent_depth": depth + 1},
        )
        elapsed = time.monotonic() - start

        result_len = len(res["result"]) if res.get("result") else 0
        _logger.info(
            "[invoke_agent] EXIT  depth=%d code=%r elapsed=%.1fs "
            "thread_id=%s error=%s result_len=%d",
            depth, agent_code, elapsed,
            res.get("thread_id"), res.get("error"), result_len,
        )
        # Strip ``result_html`` before returning to the calling LLM. The HTML
        # variant exists for programmatic callers binding output to a
        # fields.Html column; an LLM seeing both keys would waste context on
        # duplicate content and may not know which to consume. Keep ``result``
        # (markdown) as the canonical reply for chained-agent flows.
        return {
            "query": res.get("query"),
            "result": res.get("result"),
            "error": res.get("error"),
            "thread_id": res.get("thread_id"),
        }
