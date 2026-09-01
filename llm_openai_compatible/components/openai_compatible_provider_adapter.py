"""OpenAI-compatible service adapter: chat-completions-protocol image output.

Implements the ``llm.provider.adapter`` contract for
``service == "openai_compatible"``, inheriting every method from
``openai.provider.adapter`` (``llm_openai``) and overriding only :meth:`chat`
to add the raw-response parsing needed by endpoints that return generated
images inline in the chat response.

The official OpenAI Chat Completions API never does this -- image generation
is a separate endpoint (``images.generate``, already covered by
``llm.provider.adapter.test_model`` / ``llm_openai``'s ``_test_image_model``).
This is purely a third-party vendor extension: litellm, Gemini reached through
the chat-completions shim, local inference servers, and similar endpoints
that speak the OpenAI wire format but smuggle image parts into ``message``
outside the documented schema, in one of two shapes:

1. a separate ``message.images`` field (litellm / Gemini style)
2. a multi-part ``content`` list holding ``image_url`` parts

Both shapes break the official SDK's strict ``Optional[str]`` typing for
``message.content``, so the raw JSON body is read instead of using the
typed SDK response.
"""

import json
import re

from odoo.addons.component.core import Component


class OpenAICompatibleProviderAdapter(Component):
    _name = "openai_compatible.provider.adapter"
    _inherit = "openai.provider.adapter"
    _usage = "openai_compatible"

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
        """Send chat messages, with tool and image-output support."""
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

        image_output = getattr(model, "supports_image_output", False)
        client = provider.client

        if not stream and image_output:
            return self._chat_with_image_output(client, params)

        response = client.chat.completions.create(**params)

        if not stream:
            return self._process_non_streaming_response(response)
        if image_output:
            return self._process_streaming_response_with_images(provider, response)
        return self._process_streaming_response(provider, response)

    def _chat_with_image_output(self, client, params):
        """Read the raw JSON body for models that may return image parts.

        ``with_raw_response`` bypasses the SDK's strict content typing: these
        endpoints return content as a list of parts (text + images) which the
        SDK's ``Optional[str]`` field cannot parse.
        """
        raw_response = client.chat.completions.with_raw_response.create(**params)
        return self._parse_raw_chat_response(json.loads(raw_response.text))

    def _parse_raw_chat_response(self, raw_json):
        """Parse a raw chat completion, handling both image response shapes.

        1. a separate ``message.images`` field (litellm / Gemini style)
        2. a multi-part ``content`` list holding ``image_url`` parts

        Returns:
            dict with any of ``content`` (str), ``tool_calls``, ``images``
        """
        try:
            choices = raw_json.get("choices", [])
            if not choices:
                return {}
            message = choices[0].get("message", {})
        except (IndexError, AttributeError):
            return {"error": "Failed to parse raw response"}

        result = {}
        images = []

        raw_images = message.get("images")
        if isinstance(raw_images, list):
            for img_part in raw_images:
                if not isinstance(img_part, dict):
                    continue
                parsed = self._parse_data_url(self._image_part_url(img_part))
                if parsed:
                    images.append(parsed)

        content = message.get("content")
        if isinstance(content, list):
            text_parts = []
            for part in content:
                if not isinstance(part, dict):
                    continue
                if part.get("type") == "text":
                    text_parts.append(part.get("text", ""))
                elif part.get("type") == "image_url":
                    parsed = self._parse_data_url(self._image_part_url(part))
                    if parsed:
                        images.append(parsed)
            if text_parts:
                result["content"] = "\n".join(text_parts)
        elif isinstance(content, str):
            result["content"] = content

        if images:
            result["images"] = images

        tool_calls = message.get("tool_calls")
        if tool_calls:
            result["tool_calls"] = [
                {
                    "id": tc.get("id", ""),
                    "type": tc.get("type", "function"),
                    "function": {
                        "name": tc.get("function", {}).get("name", ""),
                        "arguments": tc.get("function", {}).get("arguments", ""),
                    },
                }
                for tc in tool_calls
            ]

        return result

    @staticmethod
    def _image_part_url(part):
        image_url = part.get("image_url", {})
        return image_url.get("url", "") if isinstance(image_url, dict) else ""

    @staticmethod
    def _parse_data_url(url):
        """Split a data URL into ``mimetype`` and base64 ``data``.

        A plain http(s) URL is returned as a ``url`` entry instead.
        """
        if not url:
            return None
        match = re.match(r"data:([^;]+);base64,(.+)", url, re.DOTALL)
        if match:
            return {"mimetype": match.group(1), "data": match.group(2)}
        if url.startswith(("http://", "https://")):
            return {"mimetype": "image/png", "url": url}
        return None

    def _process_streaming_response_with_images(self, provider, response_stream):
        """Streaming variant for image-capable models.

        Extension point only. Endpoints that return images through the
        chat-completions protocol compute them atomically and do not stream
        them, so today this only forwards the text and tool-call events.
        """
        yield from self._process_streaming_response(provider, response_stream)
