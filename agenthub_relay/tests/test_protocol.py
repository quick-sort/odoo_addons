from agenthub_relay.config import AgentConfig
from agenthub_relay.protocol import (
    AgentDirectory,
    authenticate_agent,
    build_stream_envelope,
    build_turn_envelope,
    hash_token,
)
from agenthub_relay.state import Delivery


def _delivery():
    return Delivery(
        delivery_id="dlv-1",
        agent_id=1,
        turn_id="turn-1",
        route={
            "agent_id": 1,
            "channel_id": 10,
            "thread_key": "thread:1",
        },
        kind="message",
        payload={"role": "user", "content": "hi"},
    )


def test_directory_verifies_token():
    token = "secret"
    directory = AgentDirectory({1: AgentConfig(1, hash_token(token))})
    assert directory.verify(1, token)
    assert not directory.verify(1, "wrong")
    assert authenticate_agent(
        directory, {"type": "auth", "agent_id": 1, "token": token}
    ) == 1
    assert (
        authenticate_agent(
            directory, {"type": "auth", "agent_id": 1, "token": "wrong"}
        )
        is None
    )


def test_stream_frame_becomes_envelope():
    delivery = _delivery()
    envelope = build_stream_envelope(
        delivery,
        {
            "stream_id": "s1",
            "seq": 1,
            "role": "assistant",
            "content": "partial",
            "final": False,
        },
    )
    assert envelope["event_type"] == "message.updated"
    assert envelope["route"]["thread_key"] == "thread:1"
    assert envelope["payload"]["stream_id"] == "s1"


def test_final_frame_becomes_message_final():
    delivery = _delivery()
    envelope = build_stream_envelope(
        delivery,
        {
            "stream_id": "s1",
            "seq": 2,
            "role": "assistant",
            "content": "done",
            "final": True,
        },
    )
    assert envelope["event_type"] == "message.final"
    assert envelope["payload"]["final"] is True


def test_turn_frame_becomes_control_event():
    delivery = _delivery()
    envelope = build_turn_envelope(delivery, "completed")
    assert envelope["event_type"] == "turn.completed"
    assert envelope["payload"]["state"] == "completed"
