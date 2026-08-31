"""Unit tests for the OpenAI service adapter.

These run without a database: the adapter is a plain class, so it can be
instantiated with ``object.__new__`` and fed mock records.

The focus is the three branches that make this adapter non-trivial -- raw
image-output parsing, streaming tool-call reassembly, and history repair --
plus the message formatting moved off ``mail.message``.
"""

import json
from types import SimpleNamespace
from unittest import mock

from odoo.tests.common import BaseCase

from odoo.addons.llm_openai.components.openai_provider_adapter import (
    OpenAIProviderAdapter,
)


def make_adapter():
    """Build the adapter without the component registry or a database."""
    return object.__new__(OpenAIProviderAdapter)


def make_message(
    role="user",
    body=None,
    body_json=None,
    texts=(),
    images=(),
    pdfs=(),
    audios=(),
    tool_calls=(),
):
    """Build a mock ``mail.message`` exposing only what the adapter uses."""
    message = mock.MagicMock()
    message.id = 7
    message.body = body
    message.body_json = body_json
    message.is_llm_user_message.return_value = {message: role == "user"}
    message.is_llm_assistant_message.return_value = {message: role == "assistant"}
    message.is_llm_tool_message.return_value = {message: role == "tool"}
    message._get_text_attachments.return_value = list(texts)
    message._get_image_attachments.return_value = list(images)
    message._get_pdf_attachments.return_value = list(pdfs)
    message._get_audio_attachments.return_value = list(audios)
    message.get_tool_calls.return_value = list(tool_calls)
    return message


def delta_tool_call(index=0, call_id=None, name=None, arguments=None, type_=None):
    """Build one streamed tool-call fragment as the SDK exposes it."""
    function = None
    if name is not None or arguments is not None:
        function = SimpleNamespace(name=name, arguments=arguments)
    return SimpleNamespace(index=index, id=call_id, type=type_, function=function)


def stream_chunk(content=None, tool_calls=None, finish_reason=None):
    delta = SimpleNamespace(content=content, tool_calls=tool_calls)
    choice = SimpleNamespace(delta=delta, finish_reason=finish_reason)
    return SimpleNamespace(choices=[choice])


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


class TestStreamingToolCalls(BaseCase):
    """Tool-call arguments arrive fragmented and must be reassembled."""

    def setUp(self):
        super().setUp()
        self.adapter = make_adapter()
        self.provider = mock.MagicMock()
        # Mirror llm_tool's helper: complete once the arguments parse as JSON.
        self.provider._is_tool_call_complete.side_effect = self._is_complete

    @staticmethod
    def _is_complete(function_data, expected_endings=("]", "}")):
        name = function_data.get("name")
        args = (function_data.get("arguments") or "").strip()
        if not name or not args:
            return False
        try:
            json.loads(args)
        except json.JSONDecodeError:
            return False
        return args.endswith(expected_endings)

    def test_text_only_stream(self):
        chunks = [stream_chunk(content="he"), stream_chunk(content="llo")]

        result = list(self.adapter._process_streaming_response(self.provider, chunks))

        self.assertEqual(result, [{"content": "he"}, {"content": "llo"}])

    def test_fragmented_arguments_are_joined(self):
        chunks = [
            stream_chunk(
                tool_calls=[delta_tool_call(call_id="c1", name="search", type_="function")],
            ),
            stream_chunk(tool_calls=[delta_tool_call(arguments='{"q":')]),
            stream_chunk(tool_calls=[delta_tool_call(arguments=' "x"}')]),
            stream_chunk(finish_reason="tool_calls"),
        ]

        result = list(self.adapter._process_streaming_response(self.provider, chunks))

        self.assertEqual(len(result), 1)
        call = result[0]["tool_calls"][0]
        self.assertEqual(call["id"], "c1")
        self.assertEqual(call["function"]["name"], "search")
        self.assertEqual(json.loads(call["function"]["arguments"]), {"q": "x"})

    def test_missing_id_gets_a_generated_one(self):
        chunks = [
            stream_chunk(
                tool_calls=[
                    delta_tool_call(call_id="", name="search", arguments='{"q": 1}'),
                ],
            ),
            stream_chunk(finish_reason="tool_calls"),
        ]

        result = list(self.adapter._process_streaming_response(self.provider, chunks))

        self.assertTrue(result[0]["tool_calls"][0]["id"])

    def test_incomplete_tool_call_yields_an_error(self):
        chunks = [
            stream_chunk(
                tool_calls=[
                    delta_tool_call(call_id="c1", name="search", arguments='{"q":'),
                ],
            ),
            stream_chunk(finish_reason="tool_calls"),
        ]

        result = list(self.adapter._process_streaming_response(self.provider, chunks))

        self.assertEqual(len(result), 1)
        self.assertIn("incomplete tool call", result[0]["error"])

    def test_multiple_calls_keep_index_order(self):
        chunks = [
            stream_chunk(
                tool_calls=[
                    delta_tool_call(index=1, call_id="c2", name="b", arguments="{}"),
                    delta_tool_call(index=0, call_id="c1", name="a", arguments="{}"),
                ],
            ),
            stream_chunk(finish_reason="tool_calls"),
        ]

        result = list(self.adapter._process_streaming_response(self.provider, chunks))

        names = [c["function"]["name"] for c in result[0]["tool_calls"]]
        self.assertEqual(names, ["a", "b"])

    def test_index_zero_is_not_replaced_by_the_counter(self):
        """``index or counter`` would collapse index 0 onto the second slot."""
        chunks = [
            stream_chunk(
                tool_calls=[
                    delta_tool_call(index=0, call_id="c1", name="a", arguments="{}"),
                    delta_tool_call(index=1, call_id="c2", name="b", arguments="{}"),
                ],
            ),
            stream_chunk(finish_reason="tool_calls"),
        ]

        result = list(self.adapter._process_streaming_response(self.provider, chunks))

        calls = result[0]["tool_calls"]
        self.assertEqual(len(calls), 2)
        self.assertEqual([c["id"] for c in calls], ["c1", "c2"])

    def test_null_index_falls_back_to_the_counter(self):
        chunks = [
            stream_chunk(
                tool_calls=[
                    delta_tool_call(index=None, call_id="c1", name="a", arguments="{}"),
                    delta_tool_call(index=None, call_id="c2", name="b", arguments="{}"),
                ],
            ),
            stream_chunk(finish_reason="tool_calls"),
        ]

        result = list(self.adapter._process_streaming_response(self.provider, chunks))

        self.assertEqual([c["id"] for c in result[0]["tool_calls"]], ["c1", "c2"])

    def test_stream_without_tools_yields_nothing_extra(self):
        chunks = [stream_chunk(content="hi"), stream_chunk(finish_reason="stop")]

        result = list(self.adapter._process_streaming_response(self.provider, chunks))

        self.assertEqual(result, [{"content": "hi"}])

    def test_exception_mid_stream_is_reported(self):
        def exploding():
            yield stream_chunk(content="hi")
            raise RuntimeError("connection lost")

        result = list(
            self.adapter._process_streaming_response(self.provider, exploding()),
        )

        self.assertEqual(result[0], {"content": "hi"})
        self.assertIn("connection lost", result[1]["error"])

    def test_chunks_without_choices_are_skipped(self):
        chunks = [SimpleNamespace(choices=[]), stream_chunk(content="hi")]

        result = list(self.adapter._process_streaming_response(self.provider, chunks))

        self.assertEqual(result, [{"content": "hi"}])


class TestNonStreamingResponse(BaseCase):
    def setUp(self):
        super().setUp()
        self.adapter = make_adapter()

    def _response(self, content=None, tool_calls=None):
        message = SimpleNamespace(content=content, tool_calls=tool_calls)
        return SimpleNamespace(choices=[SimpleNamespace(message=message)])

    def test_content_only(self):
        result = self.adapter._process_non_streaming_response(self._response("hi"))

        self.assertEqual(result, {"content": "hi"})

    def test_tool_calls(self):
        tool_call = SimpleNamespace(
            id="c1",
            type="function",
            function=SimpleNamespace(name="search", arguments='{"q": 1}'),
        )

        result = self.adapter._process_non_streaming_response(
            self._response(None, [tool_call]),
        )

        self.assertEqual(result["tool_calls"][0]["id"], "c1")
        self.assertNotIn("content", result)

    def test_empty_response(self):
        self.assertEqual(
            self.adapter._process_non_streaming_response(self._response()),
            {},
        )

    def test_broken_response_becomes_an_error(self):
        result = self.adapter._process_non_streaming_response(
            SimpleNamespace(choices=[]),
        )

        self.assertIn("error", result)


class TestFormatMessage(BaseCase):
    def setUp(self):
        super().setUp()
        self.adapter = make_adapter()

    def test_plain_user_message(self):
        result = self.adapter._format_message(make_message(body="<p>hello</p>"))

        self.assertEqual(result["role"], "user")
        self.assertEqual(result["content"].strip(), "hello")

    def test_empty_user_message_is_dropped(self):
        self.assertIsNone(self.adapter._format_message(make_message(body="  ")))

    def test_image_becomes_a_data_url(self):
        message = make_message(
            body="<p>look</p>",
            images=[{"mimetype": "image/png", "data": "AAA", "name": "a.png"}],
        )

        result = self.adapter._format_message(message, is_multimodal=True)

        text_block, image_block = result["content"]
        self.assertEqual(text_block, {"type": "text", "text": "look"})
        self.assertEqual(image_block["type"], "image_url")
        self.assertEqual(
            image_block["image_url"]["url"],
            "data:image/png;base64,AAA",
        )

    def test_images_dropped_when_not_multimodal(self):
        message = make_message(
            body="<p>look</p>",
            images=[{"mimetype": "image/png", "data": "AAA", "name": "a.png"}],
        )

        result = self.adapter._format_message(message, is_multimodal=False)

        self.assertEqual(result["content"].strip(), "look")
        message._get_image_attachments.assert_not_called()

    def test_pdf_becomes_a_file_part(self):
        message = make_message(
            body=None,
            pdfs=[{"mimetype": "application/pdf", "data": "PDF", "name": "d.pdf"}],
        )

        result = self.adapter._format_message(message, is_multimodal=True)

        text_block, file_block = result["content"]
        self.assertEqual(text_block["text"], "Please analyze these files.")
        self.assertEqual(file_block["file"]["filename"], "d.pdf")
        self.assertEqual(
            file_block["file"]["file_data"],
            "data:application/pdf;base64,PDF",
        )

    def test_audio_requires_an_audio_model(self):
        audio = {"format": "wav", "data": "WAV", "name": "a.wav"}
        message = make_message(body="<p>listen</p>", audios=[audio])

        without = self.adapter._format_message(message, is_audio_model=False)
        self.assertEqual(without["content"].strip(), "listen")
        message._get_audio_attachments.assert_not_called()

        with_audio = self.adapter._format_message(message, is_audio_model=True)
        audio_block = with_audio["content"][1]
        self.assertEqual(audio_block["type"], "input_audio")
        self.assertEqual(audio_block["input_audio"], {"data": "WAV", "format": "wav"})

    def test_text_attachment_is_inlined(self):
        message = make_message(
            body="<p>see file</p>",
            texts=[{"name": "notes.txt", "content": "body", "mimetype": "text/plain"}],
        )

        result = self.adapter._format_message(message)

        self.assertEqual(
            result["content"],
            [{"type": "text", "text": "see file\n\n--- notes.txt ---\nbody"}],
        )

    def test_assistant_message_with_tool_calls(self):
        message = make_message(
            role="assistant",
            body="on it",
            tool_calls=[
                {
                    "id": "c1",
                    "function": {"name": "search", "arguments": '{"q": 1}'},
                },
            ],
        )

        result = self.adapter._format_message(message)

        self.assertEqual(result["role"], "assistant")
        self.assertEqual(result["content"], "on it")
        self.assertEqual(result["tool_calls"][0]["type"], "function")
        self.assertEqual(result["tool_calls"][0]["function"]["name"], "search")

    def test_tool_result_message(self):
        message = make_message(
            role="tool",
            body_json={"tool_call_id": "c1", "result": {"ok": True}},
        )

        result = self.adapter._format_message(message)

        self.assertEqual(result["role"], "tool")
        self.assertEqual(result["tool_call_id"], "c1")
        self.assertEqual(json.loads(result["content"]), {"ok": True})

    def test_tool_error_message(self):
        message = make_message(
            role="tool",
            body_json={"tool_call_id": "c1", "error": "boom"},
        )

        result = self.adapter._format_message(message)

        self.assertEqual(json.loads(result["content"]), {"error": "boom"})

    def test_tool_message_without_call_id_is_dropped(self):
        message = make_message(role="tool", body_json={"result": 1})

        self.assertIsNone(self.adapter._format_message(message))

    def test_unknown_role_is_dropped(self):
        self.assertIsNone(self.adapter._format_message(make_message(role="none")))


class TestAudioModelDetection(BaseCase):
    def setUp(self):
        super().setUp()
        self.adapter = make_adapter()

    def test_audio_preview_models(self):
        for name in ("gpt-4o-audio-preview", "GPT-4O-AUDIO", "some-audio-preview-x"):
            with self.subTest(name=name):
                self.assertTrue(
                    self.adapter._is_audio_model(SimpleNamespace(name=name)),
                )

    def test_regular_models(self):
        for name in ("gpt-4o", "gpt-5", "o3-mini"):
            with self.subTest(name=name):
                self.assertFalse(
                    self.adapter._is_audio_model(SimpleNamespace(name=name)),
                )

    def test_missing_model_or_name(self):
        self.assertFalse(self.adapter._is_audio_model(None))
        self.assertFalse(self.adapter._is_audio_model(SimpleNamespace(name=None)))


class TestSchemaPatching(BaseCase):
    """Some endpoints reject an array schema whose items has no type."""

    def setUp(self):
        super().setUp()
        self.adapter = make_adapter()

    def test_bare_items_get_a_type(self):
        schema = {"properties": {"tags": {"type": "array", "items": {}}}}

        self.adapter._patch_schema_items(schema)

        self.assertEqual(schema["properties"]["tags"]["items"]["type"], "string")

    def test_existing_type_is_kept(self):
        schema = {"properties": {"n": {"type": "array", "items": {"type": "integer"}}}}

        self.adapter._patch_schema_items(schema)

        self.assertEqual(schema["properties"]["n"]["items"]["type"], "integer")

    def test_nested_and_combiners(self):
        schema = {
            "properties": {
                "outer": {
                    "type": "array",
                    "items": {"type": "array", "items": {}},
                },
            },
            "anyOf": [{"type": "array", "items": {}}],
        }

        self.adapter._patch_schema_items(schema)

        self.assertEqual(
            schema["properties"]["outer"]["items"]["items"]["type"],
            "string",
        )
        self.assertEqual(schema["anyOf"][0]["items"]["type"], "string")

    def test_non_dict_input_is_ignored(self):
        self.adapter._patch_schema_items(None)
        self.adapter._patch_schema_items(["not", "a", "dict"])


class TestFormatTools(BaseCase):
    def setUp(self):
        super().setUp()
        self.adapter = make_adapter()

    def _tool(self, name="search", description="Find", input_schema=None):
        tool = mock.MagicMock()
        tool.name = name
        tool.description = description
        tool.input_schema = input_schema
        return tool

    def test_stored_schema(self):
        schema = {"properties": {"q": {"type": "string"}}, "required": ["q"]}
        tool = self._tool(input_schema=json.dumps(schema))

        result = self.adapter.format_tools(None, [tool])

        self.assertEqual(
            result[0],
            {
                "type": "function",
                "function": {
                    "name": "search",
                    "description": "Find",
                    "parameters": {
                        "type": "object",
                        "properties": {"q": {"type": "string"}},
                        "required": ["q"],
                    },
                },
            },
        )

    def test_broken_schema_falls_back_to_generated(self):
        tool = self._tool(input_schema="{not json")
        tool.get_input_schema.return_value = {"properties": {"a": {"type": "integer"}}}

        result = self.adapter.format_tools(None, [tool])

        self.assertEqual(
            result[0]["function"]["parameters"]["properties"],
            {"a": {"type": "integer"}},
        )

    def test_no_schema_at_all_yields_empty_parameters(self):
        tool = self._tool(input_schema=False)
        tool.get_input_schema.return_value = None

        result = self.adapter.format_tools(None, [tool])

        self.assertEqual(
            result[0]["function"]["parameters"],
            {"type": "object", "properties": {}, "required": []},
        )

    def test_empty_schema_means_no_parameters(self):
        """``{}`` is a valid schema, not a missing one."""
        tool = self._tool(input_schema="{}")

        result = self.adapter.format_tools(None, [tool])

        self.assertEqual(len(result), 1)
        self.assertEqual(
            result[0]["function"]["parameters"],
            {"type": "object", "properties": {}, "required": []},
        )

    def test_unresolvable_tools_are_dropped_not_sent_as_none(self):
        """A None in the tools array would make the API reject the request."""
        good = self._tool(name="good", input_schema="{}")
        broken = self._tool(name="broken", input_schema=False)
        broken.get_input_schema.return_value = None

        with mock.patch.object(
            OpenAIProviderAdapter,
            "_tool_from_schema",
            side_effect=lambda schema, tool: None if tool.name == "broken" else {"ok": tool.name},
        ):
            result = self.adapter.format_tools(None, [good, broken])

        self.assertEqual(result, [{"ok": "good"}])

    def test_schema_generation_error_is_contained(self):
        tool = self._tool(input_schema=False)
        tool.get_input_schema.side_effect = RuntimeError("boom")

        result = self.adapter.format_tools(None, [tool])

        self.assertEqual(result[0]["function"]["name"], "search")
        self.assertEqual(result[0]["function"]["parameters"]["properties"], {})


class TestModelParsing(BaseCase):
    def setUp(self):
        super().setUp()
        self.adapter = make_adapter()

    def _model(self, model_id):
        return SimpleNamespace(id=model_id, model_dump=lambda: {"id": model_id})

    def test_embedding_models(self):
        parsed = self.adapter._parse_model(self._model("text-embedding-3-small"))

        self.assertEqual(parsed["details"]["capabilities"], ["embedding"])

    def test_vision_models(self):
        for model_id in ("gpt-4o", "gpt-4.1-mini", "o3", "gpt-5-preview"):
            with self.subTest(model_id=model_id):
                parsed = self.adapter._parse_model(self._model(model_id))

                self.assertIn("multimodal", parsed["details"]["capabilities"])

    def test_plain_chat_model(self):
        parsed = self.adapter._parse_model(self._model("gpt-3.5-turbo"))

        self.assertEqual(parsed["details"]["capabilities"], ["chat"])

    def test_name_and_details(self):
        parsed = self.adapter._parse_model(self._model("gpt-4o"))

        self.assertEqual(parsed["name"], "gpt-4o")
        self.assertEqual(parsed["details"]["id"], "gpt-4o")


class TestChatRequest(BaseCase):
    """Check the request OpenAI receives, with the SDK client mocked out."""

    def setUp(self):
        super().setUp()
        self.adapter = make_adapter()
        self.client = mock.MagicMock()
        self.client.chat.completions.create.return_value = SimpleNamespace(
            choices=[
                SimpleNamespace(
                    message=SimpleNamespace(content="hi", tool_calls=None),
                ),
            ],
        )
        self.model = SimpleNamespace(
            name="gpt-4o",
            model_use="chat",
            supports_image_output=False,
        )
        self.provider = mock.MagicMock()
        self.provider.client = self.client
        self.provider.get_model.return_value = self.model

    def _params(self):
        return self.client.chat.completions.create.call_args.kwargs

    def test_basic_request(self):
        result = self.adapter.chat(self.provider, [])

        params = self._params()
        self.assertEqual(params["model"], "gpt-4o")
        self.assertFalse(params["stream"])
        self.assertNotIn("tools", params)
        self.assertEqual(result, {"content": "hi"})

    def test_prepend_messages_go_first(self):
        self.adapter.chat(
            self.provider,
            [],
            prepend_messages=[{"role": "system", "content": "be nice"}],
        )

        self.assertEqual(
            self._params()["messages"],
            [{"role": "system", "content": "be nice"}],
        )

    def test_tools_set_tool_choice_auto(self):
        tool = mock.MagicMock()
        tool.name = "search"
        tool.description = "Find"
        tool.input_schema = "{}"

        self.adapter.chat(self.provider, [], tools=[tool])

        params = self._params()
        self.assertEqual(params["tool_choice"], "auto")
        self.assertEqual(params["tools"][0]["function"]["name"], "search")

    def test_tool_choice_override(self):
        tool = mock.MagicMock()
        tool.name = "search"
        tool.description = "Find"
        tool.input_schema = "{}"

        self.adapter.chat(self.provider, [], tools=[tool], tool_choice="none")

        self.assertEqual(self._params()["tool_choice"], "none")

    def test_image_output_uses_the_raw_response_path(self):
        self.model.supports_image_output = True
        raw = mock.MagicMock()
        raw.text = json.dumps(
            {"choices": [{"message": {"content": "drawn"}}]},
        )
        self.client.chat.completions.with_raw_response.create.return_value = raw

        result = self.adapter.chat(self.provider, [])

        self.assertEqual(result, {"content": "drawn"})
        self.client.chat.completions.create.assert_not_called()

    def test_streaming_returns_a_generator(self):
        self.client.chat.completions.create.return_value = [
            stream_chunk(content="a"),
        ]

        result = self.adapter.chat(self.provider, [], stream=True)

        self.assertEqual(list(result), [{"content": "a"}])
