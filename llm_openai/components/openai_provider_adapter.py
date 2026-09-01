"""OpenAI service adapter.

Implements the ``llm.provider.adapter`` contract for ``service == "openai"``,
following the official OpenAI API only. Third-party endpoints that speak the
same wire format but smuggle vendor extensions into the response (image parts
inline in a chat completion, for instance) are covered by
``llm_openai_compatible``, which inherits this adapter and overrides only what
differs.

Every method takes the ``llm.provider`` record as its first argument instead of
reading ``self.collection``, which keeps the parsing and formatting logic
testable without a database (see ``llm_openai/tests/``).

Two branches make this adapter larger than a plain chat client:

- **streaming tool calls** -- arguments arrive fragmented across chunks and
  have to be reassembled (:meth:`_update_tool_call_chunk`)
- **history repair** -- a tool message with no preceding assistant
  ``tool_calls`` is rejected by the API, so the history is cleaned first
  (:meth:`_validate_and_clean_messages`)
"""

import json
import logging
import uuid

from openai import OpenAI

from odoo import tools

from odoo.addons.component.core import Component

from ..utils.openai_message_validator import OpenAIMessageValidator

_logger = logging.getLogger(__name__)

# The API does not advertise capabilities, so vision support is guessed from
# the model name.
VISION_PATTERNS = (
    "gpt-4o",
    "gpt-4-turbo",
    "gpt-4.1",
    "gpt-4-vision",
    "gpt-5",
    "o1",
    "o3",
)

# Audio input is only accepted by the audio-preview family.
AUDIO_PATTERNS = (
    "audio-preview",
    "gpt-4o-audio",
)


class OpenAIProviderAdapter(Component):
    _name = "openai.provider.adapter"
    _inherit = "llm.provider.adapter"
    _usage = "openai"

    # ------------------------------------------------------------------
    # Client
    # ------------------------------------------------------------------

    def get_client(self, provider):
        return OpenAI(api_key=provider.api_key, base_url=provider.api_base or None)

    def normalize_prepend_messages(self, provider, prepend_messages):
        """OpenAI accepts both string and list content, so nothing to adapt."""
        return prepend_messages or []

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------

    def format_tools(self, provider, tool_records):
        formatted = [self._format_tool(tool) for tool in tool_records]
        # A tool whose schema could not be resolved formats to None; leaving it
        # in would make the API reject the whole request.
        return [tool for tool in formatted if tool]

    def _format_tool(self, tool):
        """Convert one ``llm.tool`` record to the OpenAI function payload."""
        try:
            if tool.input_schema:
                try:
                    schema = json.loads(tool.input_schema)
                    return self._tool_from_schema(schema, tool)
                except json.JSONDecodeError:
                    _logger.error("Invalid JSON schema for tool %s", tool.name)

            schema = tool.get_input_schema()
            if schema:
                return self._tool_from_schema(schema, tool)

            _logger.warning("Could not get schema for tool %s, using fallback", tool.name)
            return self._tool_from_schema(
                {"type": "object", "properties": {}, "required": []},
                tool,
            )
        except Exception as error:  # noqa: BLE001 - never break a chat over one tool
            _logger.error("Error formatting tool %s: %s", tool.name, error, exc_info=True)
            return self._tool_from_schema(
                {
                    "title": tool.name,
                    "description": tool.description,
                    "properties": {},
                    "required": [],
                },
                tool,
            )

    def _tool_from_schema(self, schema, tool):
        """Wrap a JSON schema in the OpenAI function envelope."""
        # Only a missing schema is a failure: ``{}`` is a valid schema meaning
        # "this tool takes no parameters".
        if schema is None:
            _logger.warning("Could not generate schema for tool %s, skipping.", tool.name)
            return None

        self._patch_schema_items(schema)

        return {
            "type": "function",
            "function": {
                "name": tool.name,
                "description": tool.description,
                "parameters": {
                    "type": "object",
                    "properties": schema.get("properties", {}),
                    "required": schema.get("required", []),
                },
            },
        }

    def _patch_schema_items(self, schema_node):
        """Give every nested ``items`` an explicit ``type``.

        Some endpoints reject an array schema whose ``items`` has no ``type``.
        Mutates ``schema_node`` in place.
        """
        if not isinstance(schema_node, dict):
            return

        items = schema_node.get("items")
        if isinstance(items, dict):
            items.setdefault("type", "string")
            self._patch_schema_items(items)

        properties = schema_node.get("properties")
        if isinstance(properties, dict):
            for prop_schema in properties.values():
                self._patch_schema_items(prop_schema)

        for combiner in ("anyOf", "allOf", "oneOf"):
            branches = schema_node.get(combiner)
            if isinstance(branches, list):
                for sub_schema in branches:
                    self._patch_schema_items(sub_schema)

    # ------------------------------------------------------------------
    # Chat
    # ------------------------------------------------------------------

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
        """Send chat messages, with tool-call support."""
        model = provider.get_model(model, "chat")

        formatted_messages = self.format_messages(provider, messages, model=model)
        if prepend_messages:
            formatted_messages = prepend_messages + formatted_messages

        params = {
            "model": model.name,
            "stream": stream,
            "messages": formatted_messages,
        }

        if tools:
            formatted_tools = self.format_tools(provider, tools)
            if formatted_tools:
                params["tools"] = formatted_tools
                params["tool_choice"] = kwargs.get("tool_choice", "auto")

        response = provider.client.chat.completions.create(**params)

        if not stream:
            return self._process_non_streaming_response(response)
        return self._process_streaming_response(provider, response)

    def _process_non_streaming_response(self, response):
        """Collapse a non-streamed completion into one standardized dict."""
        try:
            message = response.choices[0].message
            result = {}

            if message.content:
                result["content"] = message.content

            if message.tool_calls:
                result["tool_calls"] = [
                    {
                        "id": tc.id,
                        "type": tc.type,
                        "function": {
                            "name": tc.function.name,
                            "arguments": tc.function.arguments,
                        },
                    }
                    for tc in message.tool_calls
                ]

            if not result:
                _logger.warning(
                    "OpenAI non-streaming response had no content or tool calls.",
                )
            return result
        except Exception as error:  # noqa: BLE001 - surfaced to the thread as an error
            _logger.exception("Error processing OpenAI non-streaming response")
            return {"error": f"Error processing response: {error}"}

    def _process_streaming_response(self, provider, response_stream):
        """Yield ``content`` / ``tool_calls`` / ``error`` dicts from a stream.

        Text is forwarded as it arrives; tool calls are buffered because their
        arguments come fragmented, and are emitted once the stream ends.
        """
        assembled_tool_calls = {}
        stream_has_tools = False
        finish_reason = None

        try:
            for chunk in response_stream:
                choice = chunk.choices[0] if chunk.choices else None
                delta = choice.delta if choice else None
                if choice and choice.finish_reason:
                    finish_reason = choice.finish_reason

                if not delta:
                    continue

                if delta.content:
                    yield {"content": delta.content}

                if delta.tool_calls:
                    stream_has_tools = True
                    for call_counter, tool_call_chunk in enumerate(delta.tool_calls):
                        # Some endpoints omit the index; fall back to the
                        # position. Test explicitly for None: index 0 is valid
                        # and must not be replaced by the counter.
                        index = tool_call_chunk.index
                        if index is None:
                            index = call_counter
                        self._update_tool_call_chunk(
                            provider,
                            assembled_tool_calls,
                            tool_call_chunk,
                            index,
                        )

            if not stream_has_tools:
                return

            if finish_reason != "tool_calls" and (
                finish_reason == "error" or not assembled_tool_calls
            ):
                _logger.warning(
                    "OpenAI stream had tool chunks but finished with reason '%s'. "
                    "Not yielding tool calls.",
                    finish_reason,
                )
                return

            final_tool_calls = []
            for index, call_data in sorted(assembled_tool_calls.items()):
                if not call_data.get("_complete"):
                    yield {
                        "error": "Received incomplete tool call data from provider "
                        f"for tool index {index}.",
                    }
                    continue
                final_tool_calls.append(
                    {
                        # Some endpoints (e.g. Google) omit the id: generate one
                        # so the tool result can be correlated back.
                        "id": call_data.get("id", "").strip() or str(uuid.uuid4()),
                        "type": call_data.get("type", "function"),
                        "function": {
                            "name": call_data["function"]["name"],
                            "arguments": call_data["function"]["arguments"],
                        },
                    },
                )

            if final_tool_calls:
                yield {"tool_calls": final_tool_calls}
            elif assembled_tool_calls:
                _logger.warning(
                    "Stream indicated tool calls, but none were successfully assembled.",
                )

        except Exception as error:  # noqa: BLE001 - surfaced to the thread
            yield {"error": f"Internal error processing stream: {error}"}

    def _update_tool_call_chunk(
        self,
        provider,
        tool_call_chunks,
        tool_call_chunk,
        index,
    ):
        """Accumulate one streamed tool-call fragment, in place."""
        current_call = tool_call_chunks.setdefault(
            index,
            {
                "id": tool_call_chunk.id,
                "type": tool_call_chunk.type,
                "function": {"name": "", "arguments": ""},
                "_complete": False,
            },
        )

        if tool_call_chunk.id:
            current_call["id"] = tool_call_chunk.id
        if tool_call_chunk.type:
            current_call["type"] = tool_call_chunk.type

        func_chunk = tool_call_chunk.function
        if func_chunk:
            if func_chunk.name:
                current_call["function"]["name"] = func_chunk.name
            if func_chunk.arguments:
                current_call["function"]["arguments"] += func_chunk.arguments

        # _is_tool_call_complete is a service-neutral helper contributed to
        # llm.provider by the llm_tool addon.
        current_call["_complete"] = provider._is_tool_call_complete(
            current_call["function"],
            expected_endings=("]", "}"),
        )

        return tool_call_chunks

    # ------------------------------------------------------------------
    # Embeddings
    # ------------------------------------------------------------------

    def embedding(self, provider, texts, model=None):
        model = provider.get_model(model, "embedding")
        response = provider.client.embeddings.create(model=model.name, input=texts)
        return [r.embedding for r in response.data]

    # ------------------------------------------------------------------
    # Messages
    # ------------------------------------------------------------------

    def format_messages(self, provider, messages, system_prompt=None, model=None):
        """Convert a ``mail.message`` recordset to the OpenAI payload.

        ``system_prompt`` is deprecated in favour of ``prepend_messages`` but
        still honoured when passed.
        """
        is_multimodal = bool(model) and getattr(model, "supports_image_input", False)
        is_audio_model = self._is_audio_model(model)

        formatted_messages = []
        if system_prompt:
            formatted_messages.append({"role": "system", "content": system_prompt})

        for message in messages:
            formatted = self._format_message(
                message,
                is_multimodal=is_multimodal,
                is_audio_model=is_audio_model,
            )
            if formatted:
                formatted_messages.append(formatted)

        return self._validate_and_clean_messages(formatted_messages)

    @staticmethod
    def _is_audio_model(model):
        """Whether ``model`` accepts audio input parts.

        NOTE: audio attachments are still filtered out earlier, by
        ``mail.message._get_unsupported_attachments()`` in the base ``llm``
        addon, which has no notion of audio-capable models. This flag is
        therefore correct but not yet reachable end to end; opening that gate
        is a separate change in ``llm`` and ``llm_thread``.
        """
        if not model or not model.name:
            return False
        name = model.name.lower()
        return any(pattern in name for pattern in AUDIO_PATTERNS)

    def _format_message(self, message, is_multimodal=False, is_audio_model=False):
        """Format one ``mail.message`` record, or ``None`` when it has no payload.

        The attachment extraction helpers used here are service-neutral and
        live on ``mail.message`` in the base ``llm`` addon; only the assembly
        into OpenAI's shape belongs here.
        """
        body = message.body
        if body:
            body = tools.html2plaintext(body)

        if message.is_llm_user_message()[message]:
            return self._format_user_message(
                message,
                body,
                is_multimodal,
                is_audio_model,
            )
        if message.is_llm_assistant_message()[message]:
            return self._format_assistant_message(message, body)
        if message.is_llm_tool_message()[message]:
            return self._format_tool_message(message)
        return None

    @staticmethod
    def _format_user_message(message, body, is_multimodal, is_audio_model):
        texts = message._get_text_attachments()
        images = message._get_image_attachments() if is_multimodal else []
        pdfs = message._get_pdf_attachments() if is_multimodal else []
        audios = message._get_audio_attachments() if is_audio_model else []

        if not (images or pdfs or texts or audios):
            if not body or not body.strip():
                return None
            return {"role": "user", "content": body}

        content = []

        text_parts = []
        if body and body.strip():
            text_parts.append(body.strip())
        for txt in texts:
            text_parts.append(f"--- {txt['name']} ---\n{txt['content']}")

        if text_parts:
            content.append({"type": "text", "text": "\n\n".join(text_parts)})
        elif images or pdfs or audios:
            content.append({"type": "text", "text": "Please analyze these files."})

        for img in images:
            content.append(
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:{img['mimetype']};base64,{img['data']}",
                    },
                },
            )

        for pdf in pdfs:
            content.append(
                {
                    "type": "file",
                    "file": {
                        "filename": pdf["name"],
                        "file_data": f"data:{pdf['mimetype']};base64,{pdf['data']}",
                    },
                },
            )

        for audio in audios:
            content.append(
                {
                    "type": "input_audio",
                    "input_audio": {
                        "data": audio["data"],
                        "format": audio["format"],
                    },
                },
            )

        return {"role": "user", "content": content}

    @staticmethod
    def _format_assistant_message(message, body):
        formatted = {"role": "assistant", "content": body}

        tool_calls = message.get_tool_calls()
        if tool_calls:
            formatted["tool_calls"] = [
                {
                    "id": tc["id"],
                    "type": tc.get("type", "function"),
                    "function": {
                        "name": tc["function"]["name"],
                        "arguments": tc["function"]["arguments"],
                    },
                }
                for tc in tool_calls
            ]

        return formatted

    @staticmethod
    def _format_tool_message(message):
        tool_data = message.body_json
        if not tool_data:
            _logger.warning(
                "OpenAI Format: skipping tool message %s, no tool data found.",
                message.id,
            )
            return None

        tool_call_id = tool_data.get("tool_call_id")
        if not tool_call_id:
            _logger.warning(
                "OpenAI Format: skipping tool message %s, missing tool_call_id.",
                message.id,
            )
            return None

        if "result" in tool_data:
            content = json.dumps(tool_data["result"])
        elif "error" in tool_data:
            content = json.dumps({"error": tool_data["error"]})
        else:
            content = ""

        return {
            "role": "tool",
            "tool_call_id": tool_call_id,
            "content": content,
        }

    @staticmethod
    def _validate_and_clean_messages(messages):
        """Drop tool messages with no matching assistant ``tool_calls``.

        The API rejects the whole request when a tool result cannot be
        correlated, which happens for instance after a thread is truncated to
        the context window in the middle of a tool round.
        """
        validator = OpenAIMessageValidator(
            messages,
            logger=_logger,
            verbose_logging=False,
        )
        return validator.validate_and_clean()

    # ------------------------------------------------------------------
    # Model discovery
    # ------------------------------------------------------------------

    def models(self, provider, model_id=None):
        client = provider.client
        if model_id:
            yield self._parse_model(client.models.retrieve(model_id))
        else:
            for model in client.models.list().data:
                yield self._parse_model(model)

    def _parse_model(self, model):
        model_id_lower = model.id.lower()

        if "embedding" in model_id_lower:
            capabilities = ["embedding"]
        elif any(pattern in model_id_lower for pattern in VISION_PATTERNS):
            capabilities = ["chat", "multimodal"]
        else:
            capabilities = ["chat"]

        return {
            "name": model.id,
            "details": {
                "id": model.id,
                "capabilities": capabilities,
                **model.model_dump(),
            },
        }
