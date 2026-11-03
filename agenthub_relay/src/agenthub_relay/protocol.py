"""Agent WebSocket protocol helpers.

The transport wrapper lives in ``app.py``; this module keeps frame ->
envelope conversion pure so it can be tested without a socket.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Any

from .config import AgentConfig
from .envelope import dump_envelope, parse_envelope
from .state import Delivery, new_id


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


class AgentDirectory:
    def __init__(self, agents: dict[int, AgentConfig]):
        self.agents = agents

    def verify(self, agent_id: int, token: str) -> bool:
        agent = self.agents.get(int(agent_id))
        if agent is None or not agent.active or not token:
            return False
        return hmac.compare_digest(agent.token_hash, hash_token(token))

    def get(self, agent_id: int) -> AgentConfig | None:
        return self.agents.get(int(agent_id))


def authenticate_agent(
    directory: AgentDirectory, frame: dict[str, Any]
) -> int | None:
    if frame.get("type") != "auth":
        return None
    try:
        agent_id = int(frame.get("agent_id"))
    except (TypeError, ValueError):
        return None
    token = frame.get("token") or ""
    if not directory.verify(agent_id, token):
        return None
    return agent_id


def build_error(code: str, message: str) -> dict[str, Any]:
    return {"type": "error", "code": code, "message": message}


def build_stream_envelope(
    delivery: Delivery, frame: dict[str, Any]
) -> dict[str, Any]:
    stream_id = frame.get("stream_id")
    final = bool(frame.get("final", False))
    if not stream_id and not final:
        stream_id = new_id("stream")
    if final and stream_id:
        event_type = "message.final"
    elif final:
        event_type = "message.created"
    else:
        event_type = "message.updated"

    message_id = frame.get("message_id") or (
        f"msg_{delivery.turn_id}_{stream_id}"
        if stream_id
        else f"msg_{delivery.turn_id}"
    )
    message = {
        "message_id": message_id,
        "role": frame.get("role", "assistant"),
        "content": frame.get("content", ""),
        "body_json": frame.get("body_json"),
        "stream_id": stream_id,
        "seq": int(frame.get("seq", 0)),
        "final": final,
        "is_error": bool(frame.get("is_error", False)),
        "author": {"type": "agent", "id": delivery.agent_id},
        "attachments": frame.get("attachments", []),
    }
    envelope = {
        "event_version": 1,
        "event_id": frame.get("event_id") or new_id("evt"),
        "event_type": event_type,
        "source": {"type": "agent", "id": str(delivery.agent_id)},
        "route": delivery.route,
        "turn": {
            "turn_id": delivery.turn_id,
            "seq": int(frame.get("seq", 0)),
            "state": "running",
        },
        "payload": message,
        "meta": {"origin": "agent"},
    }
    return dump_envelope(parse_envelope(envelope))


def build_turn_envelope(
    delivery: Delivery, state: str, error: str | None = None
) -> dict[str, Any]:
    event_type = {
        "running": "turn.started",
        "completed": "turn.completed",
        "failed": "turn.failed",
        "cancelled": "turn.cancelled",
    }.get(state)
    if event_type is None:
        raise ValueError(f"unsupported turn state: {state}")
    envelope = {
        "event_version": 1,
        "event_id": new_id("evt"),
        "event_type": event_type,
        "source": {"type": "agent", "id": str(delivery.agent_id)},
        "route": delivery.route,
        "turn": {
            "turn_id": delivery.turn_id,
            "state": state if state != "running" else "running",
        },
        "payload": {"state": state, "error": error},
        "meta": {"origin": "agent"},
    }
    return dump_envelope(parse_envelope(envelope))
