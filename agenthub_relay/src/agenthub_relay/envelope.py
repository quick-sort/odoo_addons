"""Canonical AgentHub relay envelope.

This schema is shared by the relay, the Odoo publisher/recorder, and agent-box.
Keep it dependency-light (pydantic only) so all sides can validate the same
wire format.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

MAX_CONTENT_BYTES = 256 * 1024
MAX_BODY_JSON_BYTES = 1024 * 1024


class EventType(str, Enum):
    MESSAGE_CREATED = "message.created"
    MESSAGE_UPDATED = "message.updated"
    MESSAGE_FINAL = "message.final"
    COMMAND_CREATED = "command.created"
    TURN_STARTED = "turn.started"
    TURN_COMPLETED = "turn.completed"
    TURN_FAILED = "turn.failed"
    TURN_CANCELLED = "turn.cancelled"
    DELIVERY_CLAIMED = "delivery.claimed"
    DELIVERY_ACKED = "delivery.acked"
    DELIVERY_FAILED = "delivery.failed"
    DELIVERY_EXPIRED = "delivery.expired"
    PRESENCE_CHANGED = "presence.changed"
    ATTACHMENT_CREATED = "attachment.created"


MESSAGE_EVENTS = {
    EventType.MESSAGE_CREATED,
    EventType.MESSAGE_UPDATED,
    EventType.MESSAGE_FINAL,
}
CONTROL_EVENTS = {
    EventType.TURN_STARTED,
    EventType.TURN_COMPLETED,
    EventType.TURN_FAILED,
    EventType.TURN_CANCELLED,
    EventType.DELIVERY_CLAIMED,
    EventType.DELIVERY_ACKED,
    EventType.DELIVERY_FAILED,
    EventType.DELIVERY_EXPIRED,
}


class Source(BaseModel):
    type: Literal["channel", "odoo", "agent", "relay", "system"]
    id: str


class Route(BaseModel):
    agent_id: int | str | None = None
    channel_id: int | str | None = None
    thread_key: str | None = None
    peer_ref: str | None = None
    user_id: int | str | None = None
    reply_mode: Literal["none", "owner", "thread"] | None = None


class Turn(BaseModel):
    turn_id: str
    seq: int = 0
    state: Literal[
        "queued", "running", "completed", "failed", "cancelled", "expired"
    ] = "queued"
    attempt: int = 1
    deadline: datetime | None = None


class Author(BaseModel):
    type: Literal["user", "agent", "system"]
    id: int | str | None = None


class Attachment(BaseModel):
    attachment_id: str
    name: str
    mime: str
    size: int
    sha256: str | None = None
    url: str | None = None
    kind: str | None = None


class MessagePayload(BaseModel):
    message_id: str
    role: Literal["user", "assistant", "tool", "system"]
    content: str = ""
    body_json: dict[str, Any] | None = None
    stream_id: str | None = None
    seq: int = 0
    final: bool = True
    is_error: bool = False
    author: Author | None = None
    external_id: str | None = None
    reply_to_external_id: str | None = None
    attachments: list[Attachment] = Field(default_factory=list)
    created_at: datetime | None = None

    @field_validator("content")
    @classmethod
    def _content_size(cls, value: str) -> str:
        if len(value.encode("utf-8")) > MAX_CONTENT_BYTES:
            raise ValueError("content exceeds 256 KiB")
        return value

    @field_validator("body_json")
    @classmethod
    def _body_json_size(cls, value):
        if value is None:
            return value
        try:
            raw = json.dumps(value, ensure_ascii=False)
        except TypeError as exc:
            raise ValueError("body_json must be JSON-serializable") from exc
        if len(raw.encode("utf-8")) > MAX_BODY_JSON_BYTES:
            raise ValueError("body_json exceeds 1 MiB")
        return value

    @model_validator(mode="after")
    def _role_rules(self):
        if self.role == "tool":
            tool_call_id = (self.body_json or {}).get("tool_call_id")
            if not tool_call_id:
                raise ValueError("tool message requires body_json.tool_call_id")
        if self.role == "assistant":
            calls = (self.body_json or {}).get("tool_calls")
            if calls is not None and not isinstance(calls, list):
                raise ValueError("body_json.tool_calls must be a list")
        return self


class CommandPayload(BaseModel):
    command_id: str
    name: str
    payload: dict[str, Any] = Field(default_factory=dict)
    reply_mode: Literal["none", "owner", "thread"] = "none"
    thread_key: str | None = None
    created_by: int | str | None = None


class ControlPayload(BaseModel):
    delivery_id: str | None = None
    leg: Literal["to_agent", "to_user"] | None = None
    state: str | None = None
    attempt: int | None = None
    error: str | None = None


class PresencePayload(BaseModel):
    agent_id: int | str
    state: Literal["connecting", "online", "busy", "draining", "offline"]
    last_seen: datetime | None = None
    capacity: int | None = None
    queue_depth: int | None = None


class Meta(BaseModel):
    trace_id: str | None = None
    config_version: int | None = None
    origin: Literal["channel", "odoo", "agent", "system"] | None = None
    origin_record_id: str | None = None
    retry_count: int | None = None


class Envelope(BaseModel):
    model_config = {"extra": "ignore"}

    event_version: int = 1
    event_id: str = Field(min_length=1)
    event_type: EventType
    occurred_at: datetime = Field(
        default_factory=lambda: datetime.now(timezone.utc)
    )
    source: Source
    route: Route | None = None
    turn: Turn | None = None
    payload: dict[str, Any]
    meta: Meta = Field(default_factory=Meta)

    @model_validator(mode="after")
    def _validate_payload(self):
        if self.event_version != 1:
            raise ValueError("unsupported event_version")
        if self.event_type in MESSAGE_EVENTS:
            message = MessagePayload.model_validate(self.payload)
            if self.route is None or self.route.agent_id is None:
                raise ValueError("message events require route.agent_id")
            if self.event_type == EventType.MESSAGE_CREATED and not message.final:
                raise ValueError("message.created requires final=true")
            if self.event_type == EventType.MESSAGE_UPDATED:
                if message.final or not message.stream_id:
                    raise ValueError(
                        "message.updated requires stream_id and final=false"
                    )
            if self.event_type == EventType.MESSAGE_FINAL:
                if not message.final or not message.stream_id:
                    raise ValueError(
                        "message.final requires stream_id and final=true"
                    )
        elif self.event_type == EventType.COMMAND_CREATED:
            command = CommandPayload.model_validate(self.payload)
            if self.route is None or self.route.agent_id is None:
                raise ValueError("command.created requires route.agent_id")
            thread_key = command.thread_key or (
                self.route.thread_key if self.route else None
            )
            if command.reply_mode == "thread" and not thread_key:
                raise ValueError("reply_mode=thread requires thread_key")
        elif self.event_type == EventType.PRESENCE_CHANGED:
            PresencePayload.model_validate(self.payload)
        elif self.event_type == EventType.ATTACHMENT_CREATED:
            Attachment.model_validate(self.payload)
        elif self.event_type in CONTROL_EVENTS:
            ControlPayload.model_validate(self.payload)
            if self.route is None or self.route.agent_id is None:
                raise ValueError("control events require route.agent_id")
        return self


def parse_envelope(data: dict[str, Any]) -> Envelope:
    """Validate and return an envelope."""
    return Envelope.model_validate(data)


def dump_envelope(envelope: Envelope) -> dict[str, Any]:
    """Return a JSON-safe dict for storage/transport."""
    return envelope.model_dump(mode="json")
