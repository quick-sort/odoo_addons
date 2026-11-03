import pytest
from pydantic import ValidationError

from agenthub_relay.envelope import parse_envelope

from .helpers import command_envelope, message_envelope


def test_valid_user_message():
    envelope = parse_envelope(message_envelope())
    assert envelope.event_type.value == "message.created"
    assert envelope.route.agent_id == 1


def test_message_updated_requires_stream_id_and_non_final():
    data = message_envelope(
        event_type="message.updated",
        stream_id=None,
        final=False,
        validate=False,
    )
    with pytest.raises(ValidationError):
        parse_envelope(data)


def test_message_final_requires_stream_id():
    data = message_envelope(
        event_type="message.final",
        stream_id=None,
        final=True,
        validate=False,
    )
    with pytest.raises(ValidationError):
        parse_envelope(data)


def test_tool_message_requires_tool_call_id():
    data = message_envelope(
        role="tool", body_json={"result": "x"}, validate=False
    )
    with pytest.raises(ValidationError):
        parse_envelope(data)


def test_command_thread_reply_requires_thread_key():
    data = command_envelope(
        reply_mode="thread", thread_key=None, validate=False
    )
    with pytest.raises(ValidationError):
        parse_envelope(data)


def test_unsupported_version_rejected():
    data = message_envelope()
    data["event_version"] = 2
    with pytest.raises(ValidationError):
        parse_envelope(data)


def test_content_size_limit():
    data = message_envelope(
        content="x" * (256 * 1024 + 1), validate=False
    )
    with pytest.raises(ValidationError):
        parse_envelope(data)
