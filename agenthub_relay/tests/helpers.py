from __future__ import annotations

from agenthub_relay.envelope import dump_envelope, parse_envelope


def message_envelope(
    *,
    event_type: str = "message.created",
    source_type: str = "channel",
    event_id: str = "evt-1",
    agent_id: int = 1,
    channel_id: int | None = 10,
    thread_key: str = "thread:1",
    turn_id: str = "turn:1",
    role: str = "user",
    content: str = "hello",
    message_id: str = "msg-1",
    stream_id: str | None = None,
    seq: int = 0,
    final: bool = True,
    body_json: dict | None = None,
    validate: bool = True,
) -> dict:
    route = {
        "agent_id": agent_id,
        "channel_id": channel_id,
        "thread_key": thread_key,
        "peer_ref": "peer",
        "user_id": 5,
    }
    turn = {"turn_id": turn_id, "seq": seq, "state": "queued"}
    author_type = "user" if source_type in ("channel", "odoo") else source_type
    payload = {
        "message_id": message_id,
        "role": role,
        "content": content,
        "body_json": body_json,
        "stream_id": stream_id,
        "seq": seq,
        "final": final,
        "author": {"type": author_type, "id": 5},
    }
    data = {
        "event_version": 1,
        "event_id": event_id,
        "event_type": event_type,
        "source": {"type": source_type, "id": "test"},
        "route": route,
        "turn": turn,
        "payload": payload,
        "meta": {"origin": source_type},
    }
    return dump_envelope(parse_envelope(data)) if validate else data


def command_envelope(
    *,
    event_id: str = "cmd-evt-1",
    agent_id: int = 1,
    thread_key: str | None = None,
    command_id: str = "cmd-1",
    reply_mode: str = "none",
    turn_id: str = "turn-cmd-1",
    validate: bool = True,
) -> dict:
    data = {
        "event_version": 1,
        "event_id": event_id,
        "event_type": "command.created",
        "source": {"type": "odoo", "id": "test"},
        "route": {
            "agent_id": agent_id,
            "thread_key": thread_key,
            "reply_mode": reply_mode,
        },
        "turn": {"turn_id": turn_id},
        "payload": {
            "command_id": command_id,
            "name": "run_tests",
            "payload": {"project": "default"},
            "reply_mode": reply_mode,
            "thread_key": thread_key,
        },
        "meta": {"origin": "odoo"},
    }
    return dump_envelope(parse_envelope(data)) if validate else data


def turn_envelope(
    *,
    event_type: str = "turn.completed",
    event_id: str = "turn-evt-1",
    agent_id: int = 1,
    thread_key: str = "thread:1",
    turn_id: str = "turn:1",
    state: str = "completed",
) -> dict:
    data = {
        "event_version": 1,
        "event_id": event_id,
        "event_type": event_type,
        "source": {"type": "agent", "id": str(agent_id)},
        "route": {
            "agent_id": agent_id,
            "channel_id": 10,
            "thread_key": thread_key,
        },
        "turn": {"turn_id": turn_id, "state": state},
        "payload": {"state": state},
        "meta": {"origin": "agent"},
    }
    return dump_envelope(parse_envelope(data))


def presence_envelope(
    *,
    event_id: str = "presence-1",
    agent_id: int = 1,
    state: str = "online",
) -> dict:
    data = {
        "event_version": 1,
        "event_id": event_id,
        "event_type": "presence.changed",
        "source": {"type": "relay", "id": "test"},
        "payload": {"agent_id": agent_id, "state": state},
        "meta": {"origin": "system"},
    }
    return dump_envelope(parse_envelope(data))
