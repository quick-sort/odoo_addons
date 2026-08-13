# Copyright 2026 Rui
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

"""Runner components: the agent's orchestration loop.

The default ``react`` runner implements the classic assistant→tool→assistant
loop. It is a generator yielding the ``llm_thread`` streaming event vocabulary
(``message_create`` / ``message_chunk`` / ``message_update`` / ``tool_called`` /
``tool_succeeded`` / ``tool_failed`` / ``error`` / ``limit_reached``) and returns
the last ``mail.message`` when done. It never commits — only flushes — so the
transaction boundary stays with the caller (HTTP controller / ``queue_job``).

Lifecycle events are emitted through ``component_event`` so observers
(``agent_trace``, audit, cost guards) can attach without touching this file.
"""

import json
import logging

from odoo import _
from odoo.exceptions import UserError

from odoo.addons.component.core import AbstractComponent, Component

_logger = logging.getLogger(__name__)


class AgentRunner(AbstractComponent):
    _name = "agent.runner"
    _collection = "agent.agent"

    def run(self, agent, session, user_message):
        """Drive one agent turn. Yield events; return the last message."""
        raise NotImplementedError


class ReActRunner(Component):
    _name = "agent.runner.react"
    _inherit = "agent.runner"
    _usage = "react"

    def run(self, agent, session, user_message):
        adapter = agent.provider_id._get_agent_adapter()
        prepend = self._build_prepend(agent, session, user_message)

        last_message = user_message
        rounds = 0
        max_rounds = agent.tool_calls_max or 0

        self._notify(agent, "on_agent_start", session=session)
        try:
            while self._should_continue(last_message):
                if last_message.llm_role in ("user", "tool"):
                    last_message = yield from self._generate_assistant_response(
                        agent, session, adapter, prepend,
                    )
                elif last_message.llm_role == "assistant" and last_message.has_tool_calls():
                    for tool_call in last_message.get_tool_calls():
                        last_message = yield from self._execute_tool_call(
                            agent, session, tool_call,
                        )
                        self.env.flush_all()
                    rounds += 1
                    if max_rounds and rounds >= max_rounds:
                        _logger.warning(
                            "[agent.runner] agent=%r thread=%d hit tool_calls_max=%d",
                            agent.code or agent.name, session.id, max_rounds,
                        )
                        yield {
                            "type": "limit_reached",
                            "reason": "tool_calls_max",
                            "limit": max_rounds,
                            "rounds_executed": rounds,
                        }
                        break
                else:
                    break
        finally:
            self._notify(agent, "on_agent_end", session=session)

        return last_message

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _build_prepend(self, agent, session, incoming):
        messages = []
        for builder in agent._get_context_builders():
            try:
                messages.extend(builder.build(agent, session, incoming=incoming))
            except Exception:  # noqa: BLE001
                _logger.exception(
                    "Context builder %s failed; skipping", builder._name,
                )
        return messages

    def _should_continue(self, last_message):
        if not last_message:
            return False
        return last_message.llm_role in ("user", "tool") or (
            last_message.llm_role == "assistant" and last_message.has_tool_calls()
        )

    def _get_model(self, agent):
        return agent.model_id or agent.provider_id.get_model(model_use="chat")

    def _chat_kwargs(self, agent, session, prepend):
        kwargs = {
            "messages": session._get_llm_history(limit=agent.context_limit),
            "tools": agent.tool_ids,
            "stream": agent.use_streaming,
            "prepend_messages": prepend,
        }
        if agent.temperature is not None:
            kwargs["temperature"] = agent.temperature
        if agent.max_tokens:
            kwargs["max_tokens"] = agent.max_tokens
        return kwargs

    # ------------------------------------------------------------------
    # LLM response handling
    # ------------------------------------------------------------------

    def _generate_assistant_response(self, agent, session, adapter, prepend):
        self.env.flush_all()
        model = self._get_model(agent)
        kwargs = self._chat_kwargs(agent, session, prepend)
        self._notify(agent, "on_llm_request", session=session)

        try:
            response = adapter.chat(model, **kwargs)
        except Exception as exc:  # noqa: BLE001
            _logger.exception("LLM API error in thread %s", session.id)
            error_message, event = session._post_error_message(
                exc, title=_("Agent Error"),
            )
            yield event
            return error_message

        if agent.use_streaming:
            return (yield from self._handle_streaming(session, response))
        return self._handle_non_streaming(session, response)

    def _handle_non_streaming(self, session, response):
        content = response.get("content", "")
        tool_calls = response.get("tool_calls", [])
        if not content and not tool_calls:
            content = "No response from model"

        body_json = {}
        if content:
            body_json["content"] = content
        if tool_calls:
            body_json["tool_calls"] = tool_calls

        return session.message_post(
            body=content if content else "",
            body_json=body_json or None,
            llm_role="assistant",
            author_id=False,
        )

    def _handle_streaming(self, session, stream_response):
        message = None
        accumulated = ""
        tool_calls = []

        for chunk in stream_response:
            if chunk.get("error"):
                error_message, event = session._post_error_message(
                    chunk["error"], title=_("Agent Error"),
                )
                yield event
                return error_message

            if chunk.get("content"):
                accumulated += chunk["content"]
                if message is None:
                    message = session.message_post(
                        body="…", llm_role="assistant", author_id=False,
                    )
                    yield {
                        "type": "message_create",
                        "message": message.to_store_format(),
                    }
                message.write({"body": session._process_llm_body(accumulated)})
                yield {"type": "message_chunk", "message": message.to_store_format()}

            if chunk.get("tool_calls"):
                tool_calls.extend(chunk["tool_calls"])

        body_json = {}
        if accumulated:
            body_json["content"] = accumulated
        if tool_calls:
            body_json["tool_calls"] = tool_calls

        if tool_calls:
            if message is None:
                message = session.message_post(
                    body="",
                    body_json=body_json,
                    llm_role="assistant",
                    author_id=False,
                )
                self.env.flush_all()
                yield {
                    "type": "message_create",
                    "message": message.to_store_format(),
                }
            else:
                message.write({"body_json": body_json})
                self.env.flush_all()
                yield {
                    "type": "message_update",
                    "message": message.to_store_format(),
                }
        elif message and accumulated:
            message.write(
                {
                    "body": session._process_llm_body(accumulated),
                    "body_json": body_json,
                },
            )
            yield {"type": "message_update", "message": message.to_store_format()}
        elif message is None:
            message = session.message_post(
                body="No response from model",
                llm_role="assistant",
                author_id=False,
            )
            yield {
                "type": "message_create",
                "message": message.to_store_format(),
            }

        return message

    # ------------------------------------------------------------------
    # Tool execution
    # ------------------------------------------------------------------

    def _execute_tool_call(self, agent, session, tool_call):
        tool_message = self.env["mail.message"].post_tool_call(
            tool_call, thread_model=session,
        )
        yield {
            "type": "message_create",
            "message": tool_message.to_store_format(),
        }

        name = tool_call.get("function", {}).get("name", "unknown_tool")
        try:
            result = self._execute_tool(agent, session, tool_call)
        except Exception as exc:  # noqa: BLE001
            _logger.exception("Error executing tool %s", name)
            tool_data = tool_message.get_tool_data() or {}
            tool_data["status"] = "error"
            tool_data["error"] = str(exc)
            tool_message.write({"body_json": tool_data})
            yield {
                "type": "tool_failed",
                "tool_data": {
                    "tool_call_id": tool_call.get("id"),
                    "tool_name": name,
                    "status": "error",
                    "error": str(exc),
                },
            }
            yield {
                "type": "message_update",
                "message": tool_message.to_store_format(),
            }
            return tool_message

        tool_data = tool_message.get_tool_data() or {}
        tool_data["status"] = "completed"
        tool_data["result"] = result
        tool_message.write({"body_json": tool_data})
        yield {
            "type": "tool_succeeded",
            "tool_data": {
                "tool_call_id": tool_call.get("id"),
                "tool_name": name,
                "status": "completed",
                "result": result,
            },
        }
        yield {
            "type": "message_update",
            "message": tool_message.to_store_format(),
        }
        return tool_message

    def _execute_tool(self, agent, session, tool_call):
        function = tool_call.get("function", {})
        name = function.get("name", "")
        arguments = function.get("arguments", "{}")
        if isinstance(arguments, str):
            try:
                arguments = json.loads(arguments)
            except json.JSONDecodeError:
                arguments = {}

        tool = session.tool_ids.filtered(lambda t: t.name == name)[:1]
        if not tool:
            raise UserError(_("Tool '%s' not found in thread", name))

        self._notify(
            agent, "on_tool_call", session=session,
            tool_name=name, arguments=arguments,
        )
        result = tool._get_tool_executor().execute(tool, arguments, session=session)
        self._notify(
            agent, "on_tool_result", session=session,
            tool_name=name, result=result,
        )
        return result

    # ------------------------------------------------------------------
    # Lifecycle events
    # ------------------------------------------------------------------

    def _notify(self, agent, name, **kwargs):
        try:
            agent._event(name, collection=agent).notify(agent=agent, **kwargs)
        except Exception:  # noqa: BLE001
            # Observability must never break the run.
            _logger.exception("Error notifying agent event %s", name)
