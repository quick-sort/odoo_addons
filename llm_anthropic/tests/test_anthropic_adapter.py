"""Unit tests for the Anthropic service adapter.

These run without a database: the adapter is a plain class, so it can be
instantiated with ``object.__new__`` and fed mock records. That is the reason
the contract passes the ``llm.provider`` record as an argument instead of
having adapters read ``self.collection``.
"""

import json
from types import SimpleNamespace
from unittest import mock

from odoo.tests.common import BaseCase

from odoo.addons.llm_anthropic.components.anthropic_provider_adapter import (
    AnthropicProviderAdapter,
)


def make_adapter():
    """Build the adapter without the component registry or a database."""
    return object.__new__(AnthropicProviderAdapter)


def make_message(
    role="user",
    body=None,
    body_json=None,
    texts=(),
    images=(),
    pdfs=(),
    tool_calls=(),
):
    """Build a mock ``mail.message`` exposing only what the adapter uses."""
    message = mock.MagicMock()
    message.id = 42
    message.body = body
    message.body_json = body_json
    message.is_llm_user_message.return_value = {message: role == "user"}
    message.is_llm_assistant_message.return_value = {message: role == "assistant"}
    message.is_llm_tool_message.return_value = {message: role == "tool"}
    message._get_text_attachments.return_value = list(texts)
    message._get_image_attachments.return_value = list(images)
    message._get_pdf_attachments.return_value = list(pdfs)
    message.get_tool_calls.return_value = list(tool_calls)
    return message


def tool_call(name="do_it", arguments='{"a": 1}', call_id="call_1"):
    return {
        "id": call_id,
        "type": "function",
        "function": {"name": name, "arguments": arguments},
    }


class TestMergeConsecutiveUserMessages(BaseCase):
    """Anthropic requires alternating roles, so adjacent user turns merge."""

    def setUp(self):
        super().setUp()
        self.adapter = make_adapter()

    def merge(self, messages):
        return self.adapter._merge_consecutive_user_messages(messages)

    def test_empty(self):
        self.assertEqual(self.merge([]), [])

    def test_str_plus_str(self):
        result = self.merge(
            [
                {"role": "user", "content": "one"},
                {"role": "user", "content": "two"},
            ],
        )

        self.assertEqual(result, [{"role": "user", "content": "one\ntwo"}])

    def test_list_plus_list(self):
        result = self.merge(
            [
                {"role": "user", "content": [{"type": "text", "text": "one"}]},
                {"role": "user", "content": [{"type": "text", "text": "two"}]},
            ],
        )

        self.assertEqual(
            result,
            [
                {
                    "role": "user",
                    "content": [
                        {"type": "text", "text": "one"},
                        {"type": "text", "text": "two"},
                    ],
                },
            ],
        )

    def test_str_plus_list(self):
        result = self.merge(
            [
                {"role": "user", "content": "one"},
                {"role": "user", "content": [{"type": "text", "text": "two"}]},
            ],
        )

        self.assertEqual(
            result[0]["content"],
            [{"type": "text", "text": "one"}, {"type": "text", "text": "two"}],
        )

    def test_list_plus_str(self):
        result = self.merge(
            [
                {"role": "user", "content": [{"type": "text", "text": "one"}]},
                {"role": "user", "content": "two"},
            ],
        )

        self.assertEqual(
            result[0]["content"],
            [{"type": "text", "text": "one"}, {"type": "text", "text": "two"}],
        )

    def test_different_roles_are_not_merged(self):
        messages = [
            {"role": "user", "content": "q"},
            {"role": "assistant", "content": "a"},
            {"role": "user", "content": "q2"},
        ]

        self.assertEqual(self.merge(messages), messages)

    def test_assistant_messages_are_never_merged(self):
        messages = [
            {"role": "assistant", "content": "a"},
            {"role": "assistant", "content": "b"},
        ]

        self.assertEqual(self.merge(messages), messages)


class TestFormatMessage(BaseCase):
    def setUp(self):
        super().setUp()
        self.adapter = make_adapter()

    def test_plain_user_message(self):
        message = make_message(body="<p>hello</p>")

        result = self.adapter._format_message(message)

        self.assertEqual(result["role"], "user")
        self.assertEqual(result["content"].strip(), "hello")

    def test_empty_user_message_is_dropped(self):
        self.assertIsNone(self.adapter._format_message(make_message(body="   ")))
        self.assertIsNone(self.adapter._format_message(make_message(body=None)))

    def test_user_message_with_image_when_multimodal(self):
        message = make_message(
            body="<p>look</p>",
            images=[{"mimetype": "image/png", "data": "BASE64", "name": "a.png"}],
        )

        result = self.adapter._format_message(message, is_multimodal=True)

        image_block, text_block = result["content"]
        self.assertEqual(image_block["type"], "image")
        self.assertEqual(image_block["source"]["type"], "base64")
        self.assertEqual(image_block["source"]["media_type"], "image/png")
        self.assertEqual(image_block["source"]["data"], "BASE64")
        self.assertEqual(text_block, {"type": "text", "text": "look"})

    def test_images_are_dropped_when_not_multimodal(self):
        message = make_message(
            body="<p>look</p>",
            images=[{"mimetype": "image/png", "data": "BASE64", "name": "a.png"}],
        )

        result = self.adapter._format_message(message, is_multimodal=False)

        self.assertEqual(result["content"].strip(), "look")
        message._get_image_attachments.assert_not_called()

    def test_pdf_becomes_a_document_block(self):
        message = make_message(
            body=None,
            pdfs=[{"mimetype": "application/pdf", "data": "PDF", "name": "d.pdf"}],
        )

        result = self.adapter._format_message(message, is_multimodal=True)

        doc_block, text_block = result["content"]
        self.assertEqual(doc_block["type"], "document")
        self.assertEqual(doc_block["source"]["media_type"], "application/pdf")
        self.assertEqual(text_block["text"], "Please analyze these files.")

    def test_text_attachment_is_inlined(self):
        message = make_message(
            body="<p>see file</p>",
            texts=[{"name": "notes.txt", "content": "body text", "mimetype": "text/plain"}],
        )

        result = self.adapter._format_message(message)

        self.assertEqual(
            result["content"],
            [{"type": "text", "text": "see file\n\n--- notes.txt ---\nbody text"}],
        )

    def test_assistant_message_with_tool_call(self):
        message = make_message(
            role="assistant",
            body="working on it",
            tool_calls=[tool_call(name="search", arguments='{"q": "x"}')],
        )

        result = self.adapter._format_message(message)

        self.assertEqual(result["role"], "assistant")
        text_block, tool_block = result["content"]
        self.assertEqual(text_block, {"type": "text", "text": "working on it"})
        self.assertEqual(tool_block["type"], "tool_use")
        self.assertEqual(tool_block["id"], "call_1")
        self.assertEqual(tool_block["name"], "search")
        self.assertEqual(tool_block["input"], {"q": "x"})

    def test_assistant_tool_call_with_broken_arguments(self):
        message = make_message(
            role="assistant",
            body=None,
            tool_calls=[tool_call(arguments="not json")],
        )

        result = self.adapter._format_message(message)

        self.assertEqual(result["content"][0]["input"], {})

    def test_empty_assistant_message_is_dropped(self):
        message = make_message(role="assistant", body=None)

        self.assertIsNone(self.adapter._format_message(message))

    def test_tool_result_becomes_user_tool_result_block(self):
        message = make_message(
            role="tool",
            body_json={"tool_call_id": "call_1", "result": {"ok": True}},
        )

        result = self.adapter._format_message(message)

        self.assertEqual(result["role"], "user")
        block = result["content"][0]
        self.assertEqual(block["type"], "tool_result")
        self.assertEqual(block["tool_use_id"], "call_1")
        self.assertEqual(json.loads(block["content"]), {"ok": True})

    def test_tool_error_is_wrapped(self):
        message = make_message(
            role="tool",
            body_json={"tool_call_id": "call_1", "error": "boom"},
        )

        block = self.adapter._format_message(message)["content"][0]

        self.assertEqual(json.loads(block["content"]), {"error": "boom"})

    def test_tool_message_without_data_is_dropped(self):
        self.assertIsNone(
            self.adapter._format_message(make_message(role="tool", body_json=None)),
        )

    def test_tool_message_without_call_id_is_dropped(self):
        message = make_message(role="tool", body_json={"result": {"ok": True}})

        self.assertIsNone(self.adapter._format_message(message))

    def test_message_without_llm_role_is_dropped(self):
        self.assertIsNone(self.adapter._format_message(make_message(role="none")))


class TestFormatMessages(BaseCase):
    def setUp(self):
        super().setUp()
        self.adapter = make_adapter()

    def test_drops_empty_and_merges_users(self):
        messages = [
            make_message(body="<p>one</p>"),
            make_message(body="   "),  # dropped
            make_message(body="<p>two</p>"),
            make_message(role="assistant", body="answer"),
        ]

        result = self.adapter.format_messages(
            provider=None,
            messages=messages,
            model=SimpleNamespace(model_use="chat"),
        )

        self.assertEqual(len(result), 2)
        self.assertEqual(result[0]["role"], "user")
        self.assertEqual(result[0]["content"], "one\ntwo")
        self.assertEqual(result[1]["role"], "assistant")

    def test_multimodal_flag_comes_from_the_model(self):
        image = {"mimetype": "image/png", "data": "B64", "name": "a.png"}
        messages = [make_message(body="<p>x</p>", images=[image])]

        result = self.adapter.format_messages(
            provider=None,
            messages=messages,
            model=SimpleNamespace(model_use="multimodal"),
        )

        self.assertEqual(result[0]["content"][0]["type"], "image")

    def test_no_model_means_no_multimodal(self):
        image = {"mimetype": "image/png", "data": "B64", "name": "a.png"}
        messages = [make_message(body="<p>x</p>", images=[image])]

        result = self.adapter.format_messages(
            provider=None,
            messages=messages,
            model=None,
        )

        self.assertEqual(result[0]["content"].strip(), "x")


class TestPrependMessages(BaseCase):
    def setUp(self):
        super().setUp()
        self.adapter = make_adapter()

    def test_none_becomes_empty_list(self):
        self.assertEqual(self.adapter.normalize_prepend_messages(None, None), [])

    def test_str_and_list_content_are_kept(self):
        messages = [
            {"role": "system", "content": "be nice"},
            {"role": "user", "content": [{"type": "text", "text": "hi"}]},
        ]

        self.assertEqual(
            self.adapter.normalize_prepend_messages(None, messages),
            messages,
        )

    def test_other_content_types_pass_through_untouched(self):
        messages = [{"role": "user", "content": 42, "extra": "kept"}]

        self.assertEqual(
            self.adapter.normalize_prepend_messages(None, messages),
            messages,
        )


class TestStreamingToolCall(BaseCase):
    def setUp(self):
        super().setUp()
        self.adapter = make_adapter()

    def test_valid_json_input(self):
        result = self.adapter._finish_tool_call(
            {"id": "c1", "name": "search", "input": '{"q": "x"}'},
        )

        self.assertEqual(result["id"], "c1")
        self.assertEqual(result["type"], "function")
        self.assertEqual(result["function"]["name"], "search")
        self.assertEqual(json.loads(result["function"]["arguments"]), {"q": "x"})

    def test_empty_input_becomes_empty_object(self):
        result = self.adapter._finish_tool_call(
            {"id": "c1", "name": "search", "input": ""},
        )

        self.assertEqual(result["function"]["arguments"], "{}")

    def test_broken_json_becomes_empty_object(self):
        result = self.adapter._finish_tool_call(
            {"id": "c1", "name": "search", "input": "{oops"},
        )

        self.assertEqual(result["function"]["arguments"], "{}")


class TestModelParsing(BaseCase):
    def setUp(self):
        super().setUp()
        self.adapter = make_adapter()

    def test_claude_models_are_multimodal(self):
        for model_id in ("claude-opus-4-5", "claude-3-5-sonnet", "claude-4-haiku"):
            with self.subTest(model_id=model_id):
                parsed = self.adapter._parse_model(SimpleNamespace(id=model_id))

                self.assertIn("multimodal", parsed["details"]["capabilities"])

    def test_unknown_model_is_chat_only(self):
        parsed = self.adapter._parse_model(SimpleNamespace(id="some-other-model"))

        self.assertEqual(parsed["details"]["capabilities"], ["chat"])

    def test_details_carry_display_name_and_created_at(self):
        model = SimpleNamespace(
            id="claude-opus-4-5",
            display_name="Claude Opus 4.5",
            created_at="2026-01-01",
        )

        parsed = self.adapter._parse_model(model)

        self.assertEqual(parsed["name"], "claude-opus-4-5")
        self.assertEqual(parsed["details"]["display_name"], "Claude Opus 4.5")
        self.assertEqual(parsed["details"]["created_at"], "2026-01-01")

    def test_display_name_falls_back_to_id(self):
        parsed = self.adapter._parse_model(SimpleNamespace(id="claude-x"))

        self.assertEqual(parsed["details"]["display_name"], "claude-x")

    def test_determine_model_use(self):
        self.assertEqual(
            self.adapter.determine_model_use(None, "claude-x", ["chat", "multimodal"]),
            "multimodal",
        )
        self.assertEqual(
            self.adapter.determine_model_use(None, "claude-x", ["chat"]),
            "chat",
        )

    def test_determine_model_use_never_returns_embedding(self):
        """Anthropic ships no embedding model, unlike the generic rules."""
        self.assertEqual(
            self.adapter.determine_model_use(None, "text-embedding-3", ["embedding"]),
            "chat",
        )


class TestFormatTools(BaseCase):
    def setUp(self):
        super().setUp()
        self.adapter = make_adapter()

    def _tool(self, name="search", description="Find things", input_schema=None):
        tool = mock.MagicMock()
        tool.name = name
        tool.description = description
        tool.input_schema = input_schema
        return tool

    def test_stored_schema_is_used(self):
        schema = {
            "type": "object",
            "properties": {"q": {"type": "string"}},
            "required": ["q"],
        }
        tool = self._tool(input_schema=json.dumps(schema))

        result = self.adapter.format_tools(None, [tool])

        self.assertEqual(
            result,
            [
                {
                    "name": "search",
                    "description": "Find things",
                    "input_schema": {
                        "type": "object",
                        "properties": {"q": {"type": "string"}},
                        "required": ["q"],
                    },
                },
            ],
        )

    def test_broken_schema_yields_empty_properties(self):
        tool = self._tool(input_schema="{not json")

        result = self.adapter.format_tools(None, [tool])

        self.assertEqual(result[0]["input_schema"]["properties"], {})
        self.assertEqual(result[0]["input_schema"]["required"], [])

    def test_generated_schema_is_used_when_field_is_empty(self):
        tool = self._tool(input_schema=False)
        tool.get_input_schema.return_value = {"properties": {"a": {"type": "integer"}}}

        result = self.adapter.format_tools(None, [tool])

        self.assertEqual(
            result[0]["input_schema"]["properties"],
            {"a": {"type": "integer"}},
        )

    def test_missing_description_becomes_empty_string(self):
        tool = self._tool(description=False, input_schema="{}")

        result = self.adapter.format_tools(None, [tool])

        self.assertEqual(result[0]["description"], "")


class TestChatRequest(BaseCase):
    """Check the request Anthropic receives, with the SDK client mocked out."""

    def setUp(self):
        super().setUp()
        self.adapter = make_adapter()
        self.client = mock.MagicMock()
        self.client.messages.create.return_value = SimpleNamespace(
            content=[SimpleNamespace(type="text", text="hi")],
        )
        self.model = SimpleNamespace(name="claude-opus-4-5", model_use="chat")
        self.provider = mock.MagicMock()
        self.provider.client = self.client
        self.provider.get_model.return_value = self.model
        self.provider._extract_content_text.side_effect = lambda content: (
            content if isinstance(content, str) else ""
        )

    def _params(self):
        return self.client.messages.create.call_args.kwargs

    def test_system_prompt_is_lifted_out_of_the_messages(self):
        self.adapter.chat(
            self.provider,
            [],
            prepend_messages=[{"role": "system", "content": "be nice"}],
        )

        params = self._params()
        self.assertEqual(params["system"], "be nice")
        self.assertEqual(params["messages"], [])

    def test_non_system_prepend_messages_stay_in_the_list(self):
        self.adapter.chat(
            self.provider,
            [],
            prepend_messages=[
                {"role": "system", "content": "be nice"},
                {"role": "user", "content": "context"},
            ],
        )

        params = self._params()
        self.assertEqual(params["messages"], [{"role": "user", "content": "context"}])
        self.assertNotIn("system", [m["role"] for m in params["messages"]])

    def test_default_max_tokens(self):
        self.adapter.chat(self.provider, [])

        self.assertEqual(self._params()["max_tokens"], 4096)

    def test_max_tokens_override(self):
        self.adapter.chat(self.provider, [], max_tokens=16)

        self.assertEqual(self._params()["max_tokens"], 16)

    def test_extended_thinking_is_off_by_default(self):
        self.adapter.chat(self.provider, [])

        self.assertNotIn("thinking", self._params())

    def test_extended_thinking_sets_budget(self):
        self.adapter.chat(self.provider, [], extended_thinking=True)

        self.assertEqual(
            self._params()["thinking"],
            {"type": "enabled", "budget_tokens": 10000},
        )

    def test_no_tools_key_without_tools(self):
        self.adapter.chat(self.provider, [])

        self.assertNotIn("tools", self._params())

    def test_response_blocks_are_collapsed(self):
        self.client.messages.create.return_value = SimpleNamespace(
            content=[
                SimpleNamespace(type="thinking", thinking="hmm"),
                SimpleNamespace(type="text", text="part one "),
                SimpleNamespace(type="text", text="part two"),
                SimpleNamespace(
                    type="tool_use",
                    id="c1",
                    name="search",
                    input={"q": "x"},
                ),
            ],
        )

        result = self.adapter.chat(self.provider, [])

        self.assertEqual(result["content"], "part one part two")
        self.assertEqual(result["thinking"], "hmm")
        self.assertEqual(result["tool_calls"][0]["function"]["name"], "search")
        self.assertEqual(
            json.loads(result["tool_calls"][0]["function"]["arguments"]),
            {"q": "x"},
        )
