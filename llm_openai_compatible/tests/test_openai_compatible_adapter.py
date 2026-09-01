"""Unit tests for the OpenAI-compatible service adapter.

Runs without a database: the adapter is a plain class, so it can be
instantiated with ``object.__new__`` and fed mock records. Covers only what
this adapter adds over ``openai.provider.adapter`` -- chat-completions-protocol
image output, a vendor extension the official OpenAI API does not have.
"""

import json
from types import SimpleNamespace
from unittest import mock

from odoo.tests.common import BaseCase

from odoo.addons.llm_openai_compatible.components.openai_compatible_provider_adapter import (
    OpenAICompatibleProviderAdapter,
)


def make_adapter():
    """Build the adapter without the component registry or a database."""
    return object.__new__(OpenAICompatibleProviderAdapter)


class TestParseRawChatResponse(BaseCase):
    """Image output arrives in two different shapes depending on the endpoint."""

    def setUp(self):
        super().setUp()
        self.adapter = make_adapter()

    def test_plain_string_content(self):
        raw = {"choices": [{"message": {"content": "hello"}}]}

        self.assertEqual(self.adapter._parse_raw_chat_response(raw), {"content": "hello"})

    def test_no_choices(self):
        self.assertEqual(self.adapter._parse_raw_chat_response({"choices": []}), {})

    def test_images_in_separate_field(self):
        raw = {
            "choices": [
                {
                    "message": {
                        "content": "here you go",
                        "images": [
                            {
                                "image_url": {
                                    "url": "data:image/png;base64,AAAA",
                                },
                            },
                        ],
                    },
                },
            ],
        }

        result = self.adapter._parse_raw_chat_response(raw)

        self.assertEqual(result["content"], "here you go")
        self.assertEqual(result["images"], [{"mimetype": "image/png", "data": "AAAA"}])

    def test_images_in_multipart_content(self):
        raw = {
            "choices": [
                {
                    "message": {
                        "content": [
                            {"type": "text", "text": "part one"},
                            {
                                "type": "image_url",
                                "image_url": {"url": "data:image/jpeg;base64,BBBB"},
                            },
                            {"type": "text", "text": "part two"},
                        ],
                    },
                },
            ],
        }

        result = self.adapter._parse_raw_chat_response(raw)

        self.assertEqual(result["content"], "part one\npart two")
        self.assertEqual(result["images"], [{"mimetype": "image/jpeg", "data": "BBBB"}])

    def test_multipart_without_text_has_no_content_key(self):
        raw = {
            "choices": [
                {
                    "message": {
                        "content": [
                            {
                                "type": "image_url",
                                "image_url": {"url": "data:image/png;base64,CCCC"},
                            },
                        ],
                    },
                },
            ],
        }

        result = self.adapter._parse_raw_chat_response(raw)

        self.assertNotIn("content", result)
        self.assertEqual(len(result["images"]), 1)

    def test_malformed_parts_are_skipped(self):
        raw = {
            "choices": [
                {
                    "message": {
                        "content": ["not a dict", {"type": "text", "text": "kept"}],
                        "images": ["not a dict", {"image_url": "not a dict"}],
                    },
                },
            ],
        }

        result = self.adapter._parse_raw_chat_response(raw)

        self.assertEqual(result["content"], "kept")
        self.assertNotIn("images", result)

    def test_tool_calls_are_normalized(self):
        raw = {
            "choices": [
                {
                    "message": {
                        "tool_calls": [
                            {
                                "id": "c1",
                                "function": {"name": "search", "arguments": "{}"},
                            },
                        ],
                    },
                },
            ],
        }

        result = self.adapter._parse_raw_chat_response(raw)

        self.assertEqual(
            result["tool_calls"],
            [
                {
                    "id": "c1",
                    "type": "function",
                    "function": {"name": "search", "arguments": "{}"},
                },
            ],
        )


class TestParseDataUrl(BaseCase):
    def setUp(self):
        super().setUp()
        self.adapter = make_adapter()

    def test_base64_data_url(self):
        self.assertEqual(
            self.adapter._parse_data_url("data:image/webp;base64,ZZZ"),
            {"mimetype": "image/webp", "data": "ZZZ"},
        )

    def test_http_url_is_passed_through(self):
        self.assertEqual(
            self.adapter._parse_data_url("https://example.com/a.png"),
            {"mimetype": "image/png", "url": "https://example.com/a.png"},
        )

    def test_empty_and_unknown(self):
        self.assertIsNone(self.adapter._parse_data_url(""))
        self.assertIsNone(self.adapter._parse_data_url("ftp://nope"))


class TestChatImageOutput(BaseCase):
    """End-to-end: ``chat()`` routes image-capable models through the raw path.

    ``format_messages``/``format_tools`` are inherited from
    ``openai.provider.adapter`` through the component framework's class
    merging, which ``object.__new__`` does not perform (it instantiates only
    this class, not the merged one the component registry builds). They are
    mocked here since this test targets the image-output branch, not message
    formatting -- already covered by ``llm_openai/tests/``.
    """

    def setUp(self):
        super().setUp()
        self.adapter = make_adapter()
        self.adapter.format_messages = mock.MagicMock(return_value=[])
        self.client = mock.MagicMock()
        self.client.chat.completions.create.return_value = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="hi", tool_calls=None),
                ),
            ],
        )
        self.model = SimpleNamespace(
            name="gemini-image-shim",
            model_use="chat",
            supports_image_output=True,
        )
        self.provider = mock.MagicMock()
        self.provider.client = self.client
        self.provider.get_model.return_value = self.model

    def test_image_output_uses_the_raw_response_path(self):
        raw = mock.MagicMock()
        raw.text = json.dumps(
            {"choices": [{"message": {"content": "drawn"}}]},
        )
        self.client.chat.completions.with_raw_response.create.return_value = raw

        result = self.adapter.chat(self.provider, [])

        self.assertEqual(result, {"content": "drawn"})
        self.client.chat.completions.create.assert_not_called()
