"""Anthropic Claude service adapter.

Implements the ``llm.provider.adapter`` contract for ``service == "anthropic"``,
strictly following the official Anthropic Messages API.

Every method takes the ``llm.provider`` record as its first argument instead of
reading ``self.collection``, which keeps the pure formatting and parsing logic
testable without a database (see ``llm_anthropic/tests/``).

Key differences from the OpenAI-shaped protocol:

- the system prompt is a separate ``system`` parameter, not a message
- tools use ``{"name", "description", "input_schema"}``
- responses are an array of content blocks, not a single content string
- tool calls arrive as a ``tool_use`` block, tool results are sent back as a
  ``tool_result`` block inside a ``user`` message (failed tools set
  ``is_error``), and orphaned blocks are dropped because the API rejects an
  unpaired ``tool_result`` or unanswered ``tool_use``
- consecutive user messages must be merged
"""

import json
import logging

from anthropic import Anthropic

from odoo import _, tools
from odoo.exceptions import UserError

from odoo.addons.component.core import Component

_logger = logging.getLogger(__name__)

DEFAULT_MAX_TOKENS = 4096
DEFAULT_THINKING_BUDGET = 10000


class AnthropicProviderAdapter(Component):
    _name = "anthropic.provider.adapter"
    _inherit = "llm.provider.adapter"
    _usage = "anthropic"

    # ------------------------------------------------------------------
    # Client
    # ------------------------------------------------------------------

    def get_client(self, provider):
        if not provider.api_key:
            raise UserError(_("API key is required for Anthropic provider"))
        return Anthropic(api_key=provider.api_key, base_url=provider.api_base or None)

    # ------------------------------------------------------------------
    # Chat
    # ------------------------------------------------------------------

    def normalize_prepend_messages(self, provider, prepend_messages):
        """Normalize pre-formatted messages.

        System messages are kept in the list and pulled out later by
        :meth:`chat`, so that every message type is handled in one place.
        """
        if not prepend_messages:
            return []

        normalized = []
        for msg in prepend_messages:
            content = msg.get("content", "")
            if isinstance(content, (str, list)):
                normalized.append({"role": msg["role"], "content": content})
            else:
                normalized.append(msg)

        return normalized

    def chat(
        self,
        provider,
        messages,
        model=None,
        stream=False,
        tools=None,
        prepend_messages=None,
        **kwargs,
    ):
        """Send chat messages to Anthropic Claude.

        Returns:
            Generator of chunk dicts when ``stream``, else a dict with
            ``content`` / ``tool_calls`` / ``thinking`` keys.
        """
        model = provider.get_model(model, "chat")
        formatted_messages = self.format_messages(provider, messages, model=model)

        max_tokens = kwargs.get("max_tokens", DEFAULT_MAX_TOKENS)
        system_content = None

        if prepend_messages:
            # The system prompt is a request parameter, not a message: every
            # system entry is lifted out of the list and joined.
            system_parts = [
                provider._extract_content_text(msg.get("content", ""))
                for msg in prepend_messages
                if msg.get("role") == "system"
            ]
            non_system_prepend = [
                m for m in prepend_messages if m.get("role") != "system"
            ]
            formatted_messages = non_system_prepend + formatted_messages
            if any(system_parts):
                system_content = "\n\n".join(p for p in system_parts if p)

        params = {
            "model": model.name,
            "messages": formatted_messages,
            "max_tokens": max_tokens,
        }

        if system_content:
            params["system"] = system_content

        if tools:
            formatted_tools = self.format_tools(provider, tools)
            if formatted_tools:
                params["tools"] = formatted_tools

        if kwargs.get("extended_thinking"):
            budget_tokens = kwargs.get("thinking_budget", DEFAULT_THINKING_BUDGET)
            params["thinking"] = {
                "type": "enabled",
                "budget_tokens": budget_tokens,
            }
            # The API rejects ``max_tokens <= thinking.budget_tokens``.
            if max_tokens <= budget_tokens:
                max_tokens = budget_tokens + DEFAULT_MAX_TOKENS
                params["max_tokens"] = max_tokens

        client = provider.client
        if stream:
            return self._stream_response(client, params)
        return self._process_response(client, params)

    def _process_response(self, client, params):
        """Collapse a non-streamed block array into one result dict."""
        response = client.messages.create(**params)
        result = {}
        thinking_content = []

        for block in response.content:
            if block.type == "thinking":
                thinking_content.append(block.thinking)
            elif block.type == "text":
                result["content"] = result.get("content", "") + block.text
            elif block.type == "tool_use":
                result.setdefault("tool_calls", []).append(
                    {
                        "id": block.id,
                        "type": "function",
                        "function": {
                            "name": block.name,
                            "arguments": json.dumps(block.input),
                        },
                    },
                )

        if thinking_content:
            result["thinking"] = "\n".join(thinking_content)

        return result

    def _stream_response(self, client, params):
        """Yield ``content`` / ``thinking`` / ``tool_calls`` chunk dicts."""
        with client.messages.stream(**params) as stream:
            tool_calls = {}

            for event in stream:
                if event.type == "content_block_start":
                    if event.content_block.type == "tool_use":
                        tool_calls[event.index] = {
                            "id": event.content_block.id,
                            "name": event.content_block.name,
                            "input": "",
                        }

                elif event.type == "content_block_delta":
                    if hasattr(event.delta, "text"):
                        yield {"content": event.delta.text}
                    elif hasattr(event.delta, "thinking"):
                        yield {"thinking": event.delta.thinking}
                    elif hasattr(event.delta, "partial_json"):
                        if event.index in tool_calls:
                            tool_calls[event.index]["input"] += event.delta.partial_json

                elif event.type == "content_block_stop":
                    if event.index in tool_calls:
                        tc = tool_calls.pop(event.index)
                        yield {"tool_calls": [self._finish_tool_call(tc)]}

    @staticmethod
    def _finish_tool_call(tool_call):
        """Turn an assembled streaming tool_use block into a tool call dict."""
        try:
            parsed_input = json.loads(tool_call["input"]) if tool_call["input"] else {}
        except json.JSONDecodeError:
            parsed_input = {}

        return {
            "id": tool_call["id"],
            "type": "function",
            "function": {
                "name": tool_call["name"],
                "arguments": json.dumps(parsed_input),
            },
        }

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------

    def format_tools(self, provider, tool_records):
        """Convert an ``llm.tool`` recordset to the Anthropic tool payload."""
        formatted = []
        for tool in tool_records:
            try:
                if tool.input_schema:
                    schema = json.loads(tool.input_schema)
                else:
                    schema = (
                        tool.get_input_schema()
                        if hasattr(tool, "get_input_schema")
                        else {}
                    )
            except (json.JSONDecodeError, TypeError):
                schema = {}

            formatted.append(
                {
                    "name": tool.name,
                    "description": tool.description or "",
                    "input_schema": {
                        "type": "object",
                        "properties": schema.get("properties", {}),
                        "required": schema.get("required", []),
                    },
                },
            )

        return formatted

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------

    def format_messages(self, provider, messages, system_prompt=None, model=None):
        """Convert a ``mail.message`` recordset to the Anthropic payload.

        ``system_prompt`` is accepted for contract compatibility but ignored:
        Anthropic takes the system prompt as a separate request parameter, set
        by :meth:`chat`.
        """
        is_multimodal = bool(model) and getattr(model, "supports_image_input", False)

        formatted_messages = [
            formatted
            for message in messages
            if (formatted := self._format_message(message, is_multimodal))
        ]

        cleaned = self._drop_orphaned_tool_blocks(formatted_messages)
        return self._merge_consecutive_user_messages(cleaned)

    @staticmethod
    def _drop_orphaned_tool_blocks(messages):
        """Enforce the ``tool_use``/``tool_result`` pairing the API requires.

        A ``tool_result`` whose ``tool_use`` is missing (thread truncated in
        the middle of a tool round) and an unanswered ``tool_use`` both make
        the API reject the whole request. Orphaned blocks are dropped, along
        with messages left empty by the cleanup. Duplicate results for the
        same ``tool_use`` are rejected as well -- the first one wins.
        """
        use_ids = {
            block["id"]
            for msg in messages
            if msg.get("role") == "assistant" and isinstance(msg.get("content"), list)
            for block in msg["content"]
            if block.get("type") == "tool_use"
        }
        result_ids = {
            block["tool_use_id"]
            for msg in messages
            if msg.get("role") == "user" and isinstance(msg.get("content"), list)
            for block in msg["content"]
            if block.get("type") == "tool_result"
        }

        seen_result_ids = set()
        cleaned = []

        for msg in messages:
            content = msg.get("content")
            if not isinstance(content, list):
                cleaned.append(msg)
                continue

            kept_blocks = []
            for block in content:
                block_type = block.get("type")
                if block_type == "tool_result":
                    tool_use_id = block.get("tool_use_id")
                    if (
                        tool_use_id not in use_ids
                        or tool_use_id in seen_result_ids
                    ):
                        _logger.warning(
                            "Anthropic Format: dropping tool_result %s (%s).",
                            tool_use_id,
                            "duplicate" if tool_use_id in seen_result_ids
                            else "no matching tool_use",
                        )
                        continue
                    seen_result_ids.add(tool_use_id)
                elif block_type == "tool_use":
                    if block.get("id") not in result_ids:
                        _logger.warning(
                            "Anthropic Format: dropping unanswered tool_use %s.",
                            block.get("id"),
                        )
                        continue
                kept_blocks.append(block)

            if kept_blocks:
                cleaned.append({**msg, "content": kept_blocks})

        return cleaned

    def _format_message(self, message, is_multimodal=False):
        """Format one ``mail.message`` record, or ``None`` when it has no payload.

        The attachment extraction helpers used here
        (``_get_image_attachments`` and friends) are service-neutral and live
        on ``mail.message`` in the base ``llm`` addon; only the assembly into
        Anthropic's block format belongs here.
        """
        body = message.body
        if body:
            body = tools.html2plaintext(body)

        if message.is_llm_user_message()[message]:
            return self._format_user_message(message, body, is_multimodal)
        if message.is_llm_agent_message()[message]:
            return self._format_agent_message(message, body)
        if message.is_llm_tool_message()[message]:
            return self._format_tool_message(message)
        return None

    @staticmethod
    def _format_user_message(message, body, is_multimodal):
        texts = message._get_text_attachments()
        images = message._get_image_attachments() if is_multimodal else []
        pdfs = message._get_pdf_attachments() if is_multimodal else []

        if not (images or pdfs or texts):
            if not body or not body.strip():
                return None
            return {"role": "user", "content": body}

        content = []

        for img in images:
            content.append(
                {
                    "type": "image",
                    "source": {
                        "type": "base64",
                        "media_type": img["mimetype"],
                        "data": img["data"],
                    },
                },
            )

        for pdf in pdfs:
            content.append(
                {
                    "type": "document",
                    "source": {
                        "type": "base64",
                        "media_type": pdf["mimetype"],
                        "data": pdf["data"],
                    },
                },
            )

        text_parts = []
        if body and body.strip():
            text_parts.append(body.strip())
        for txt in texts:
            text_parts.append(f"--- {txt['name']} ---\n{txt['content']}")

        if text_parts:
            content.append({"type": "text", "text": "\n\n".join(text_parts)})
        elif images or pdfs:
            content.append({"type": "text", "text": "Please analyze these files."})

        return {"role": "user", "content": content}

    @staticmethod
    def _format_agent_message(message, body):
        content_blocks = []

        if body:
            content_blocks.append({"type": "text", "text": body})

        for tool_call in message.get_tool_calls() or []:
            try:
                tool_input = json.loads(tool_call["function"]["arguments"])
            except (json.JSONDecodeError, KeyError, TypeError):
                tool_input = {}

            content_blocks.append(
                {
                    "type": "tool_use",
                    "id": tool_call["id"],
                    "name": tool_call["function"]["name"],
                    "input": tool_input,
                },
            )

        return {"role": "assistant", "content": content_blocks} if content_blocks else None

    @staticmethod
    def _format_tool_message(message):
        """Tool results go back as a ``tool_result`` block in a user message."""
        tool_data = message.body_json
        if not tool_data:
            _logger.warning(
                "Anthropic Format: skipping tool message %s, no tool data found.",
                message.id,
            )
            return None

        tool_call_id = tool_data.get("tool_call_id")
        if not tool_call_id:
            _logger.warning(
                "Anthropic Format: skipping tool message %s, missing tool_call_id.",
                message.id,
            )
            return None

        block = {"type": "tool_result", "tool_use_id": tool_call_id}
        if "result" in tool_data:
            block["content"] = json.dumps(tool_data["result"])
        elif "error" in tool_data:
            # ``is_error`` is the protocol's way to report a failed tool.
            block["content"] = json.dumps({"error": tool_data["error"]})
            block["is_error"] = True
        else:
            block["content"] = ""

        return {"role": "user", "content": [block]}

    @staticmethod
    def _merge_consecutive_user_messages(messages):
        """Merge adjacent user messages, as Anthropic requires alternating roles."""
        if not messages:
            return []

        merged = []
        for msg in messages:
            if not (merged and merged[-1]["role"] == msg["role"] == "user"):
                merged.append(msg)
                continue

            prev_content = merged[-1]["content"]
            curr_content = msg["content"]

            if isinstance(prev_content, str) and isinstance(curr_content, str):
                merged[-1]["content"] = prev_content + "\n" + curr_content
            elif isinstance(prev_content, list) and isinstance(curr_content, list):
                merged[-1]["content"] = prev_content + curr_content
            elif isinstance(prev_content, str) and isinstance(curr_content, list):
                merged[-1]["content"] = [
                    {"type": "text", "text": prev_content},
                ] + curr_content
            else:  # list + str
                merged[-1]["content"] = prev_content + [
                    {"type": "text", "text": curr_content},
                ]

        return merged

    # ------------------------------------------------------------------
    # Model discovery
    # ------------------------------------------------------------------

    def models(self, provider, model_id=None):
        """Yield ``{"name", "details"}`` dicts for the available models."""
        client = provider.client
        if model_id:
            yield self._parse_model(client.models.retrieve(model_id))
        else:
            for model in client.models.list().data:
                yield self._parse_model(model)

    @staticmethod
    def _parse_model(model):
        capabilities = ["chat"]

        model_id = model.id.lower()
        if "opus" in model_id or "claude-3" in model_id or "claude-4" in model_id:
            capabilities.append("multimodal")

        return {
            "name": model.id,
            "details": {
                "id": model.id,
                "display_name": getattr(model, "display_name", model.id),
                "capabilities": capabilities,
                "created_at": str(getattr(model, "created_at", "")),
            },
        }
