"""In-memory relay state: turns, deliveries, outbox, presence, record feed.

This is the v1 skeleton store. Its public methods are the contract a Redis /
NATS-backed store should implement later.
"""

from __future__ import annotations

import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Any


MESSAGE_EVENT_TYPES = {"message.created", "message.updated", "message.final"}
TERMINAL_TURN_STATES = {"completed", "failed", "cancelled", "expired"}


def new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


@dataclass
class Turn:
    turn_id: str
    thread_key: str
    agent_id: int
    route: dict[str, Any] = field(default_factory=dict)
    state: str = "queued"
    inbound: dict[str, Any] | None = None
    command: dict[str, Any] | None = None
    created_at: float = field(default_factory=time.time)
    finished_at: float | None = None
    error: str | None = None


@dataclass
class Delivery:
    delivery_id: str
    agent_id: int
    turn_id: str
    route: dict[str, Any]
    kind: str  # message | command
    payload: dict[str, Any]
    state: str = "queued"
    attempt: int = 0
    lease_until: float | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)

    def deliver_frame(self) -> dict[str, Any]:
        frame = {
            "type": "deliver",
            "delivery_id": self.delivery_id,
            "turn": {
                "turn_id": self.turn_id,
                "thread_key": self.route.get("thread_key"),
                "state": "running",
            },
            "kind": self.kind,
        }
        if self.kind == "command":
            frame["command"] = self.payload
        else:
            frame["message"] = self.payload
        return frame


@dataclass
class Outbox:
    outbox_id: str
    channel_id: int
    thread_key: str
    turn_id: str
    message: dict[str, Any]
    state: str = "pending"
    attempt: int = 0
    lease_until: float | None = None
    error: str | None = None
    created_at: float = field(default_factory=time.time)


class RelayState:
    def __init__(self, lease_seconds: float = 60.0, max_attempts: int = 5):
        self.lease_seconds = lease_seconds
        self.max_attempts = max_attempts
        self.turns: dict[str, Turn] = {}
        self.deliveries: dict[str, Delivery] = {}
        self.outbox: dict[str, Outbox] = {}
        self.events: list[dict[str, Any]] = []
        self.event_ids: dict[str, float] = {}
        self.message_keys: set[tuple[Any, ...]] = set()
        self.outbox_keys: set[tuple[str, str]] = set()
        self.active_turns: dict[str, str] = {}
        self.backlog: dict[str, deque[str]] = defaultdict(deque)
        self.presence: dict[int, dict[str, Any]] = {}
        self.record_cursor_acked = 0

    # -- ingest ---------------------------------------------------------

    def ingest(self, envelope: dict[str, Any]) -> str:
        event_id = envelope.get("event_id")
        if not event_id:
            raise ValueError("event_id is required")
        if event_id in self.event_ids:
            return "duplicate"
        self.event_ids[event_id] = time.time()

        event_type = envelope.get("event_type")
        if event_type == "presence.changed":
            self._ingest_presence(envelope.get("payload") or {})
            return "accepted"

        if event_type in MESSAGE_EVENT_TYPES:
            key = self._message_key(envelope)
            if key in self.message_keys:
                return "duplicate"
            self.message_keys.add(key)
            self.events.append(envelope)
            return self._ingest_message(envelope)

        self.events.append(envelope)
        if event_type == "command.created":
            return self._ingest_command(envelope)
        if isinstance(event_type, str) and event_type.startswith("turn."):
            self._ingest_turn(envelope)
            return "accepted"
        if isinstance(event_type, str) and event_type.startswith("delivery."):
            self._ingest_delivery(envelope)
            return "accepted"
        return "accepted"

    @staticmethod
    def _message_key(envelope: dict[str, Any]) -> tuple[Any, ...]:
        route = envelope.get("route") or {}
        turn = envelope.get("turn") or {}
        message = envelope.get("payload") or {}
        return (
            route.get("thread_key"),
            turn.get("turn_id"),
            message.get("stream_id") or message.get("message_id"),
            int(message.get("seq", 0)),
        )

    def _ingest_message(self, envelope: dict[str, Any]) -> str:
        event_type = envelope.get("event_type")
        source = envelope.get("source") or {}
        route = envelope.get("route") or {}
        turn_meta = envelope.get("turn") or {}
        message = envelope.get("payload") or {}
        meta = envelope.get("meta") or {}

        if source.get("type") == "agent":
            self._ingest_agent_message(
                event_type, route, turn_meta, message, meta
            )
            return "accepted"

        if event_type != "message.created":
            return "accepted"
        if route.get("agent_id") is None or not route.get("thread_key"):
            return "accepted"

        turn_id = turn_meta.get("turn_id") or new_id("turn")
        if turn_id in self.turns:
            return "duplicate"
        turn = Turn(
            turn_id=turn_id,
            thread_key=route["thread_key"],
            agent_id=int(route["agent_id"]),
            route=dict(route),
            inbound=message,
        )
        self.turns[turn_id] = turn
        self._schedule_turn(turn)
        return "accepted"

    def _ingest_agent_message(
        self,
        event_type: str,
        route: dict[str, Any],
        turn_meta: dict[str, Any],
        message: dict[str, Any],
        meta: dict[str, Any] | None = None,
    ) -> None:
        turn_id = turn_meta.get("turn_id")
        turn = self.turns.get(turn_id) if turn_id else None
        if turn is None:
            turn = Turn(
                turn_id=turn_id or new_id("turn"),
                thread_key=route.get("thread_key") or "",
                agent_id=int(route.get("agent_id") or 0),
                route=dict(route),
                state="running",
            )
            self.turns[turn.turn_id] = turn
        turn.state = "running"

        if not message.get("final"):
            return
        if (meta or {}).get("origin") == "channel":
            # The channel transport already delivered this reply to the user;
            # re-queueing it would echo it back over the same socket.
            return
        if turn.command:
            reply_mode = (turn.command or {}).get("reply_mode", "none")
        else:
            reply_mode = "thread"
        if (
            reply_mode == "thread"
            and route.get("channel_id") is not None
            and message.get("role") in ("assistant", "system")
        ):
            self._create_outbox(turn, route, message)

    def _ingest_command(self, envelope: dict[str, Any]) -> str:
        route = envelope.get("route") or {}
        command = envelope.get("payload") or {}
        agent_id = route.get("agent_id")
        if agent_id is None:
            return "accepted"
        thread_key = (
            route.get("thread_key")
            or command.get("thread_key")
            or f"command:{command.get('command_id', new_id('cmd'))}"
        )
        turn_id = (envelope.get("turn") or {}).get("turn_id") or new_id("turn")
        if turn_id in self.turns:
            return "duplicate"
        turn = Turn(
            turn_id=turn_id,
            thread_key=thread_key,
            agent_id=int(agent_id),
            route=dict(route),
            command=command,
        )
        self.turns[turn_id] = turn
        self._schedule_turn(turn)
        return "accepted"

    def _ingest_turn(self, envelope: dict[str, Any]) -> None:
        event_type = envelope.get("event_type") or ""
        turn_meta = envelope.get("turn") or {}
        payload = envelope.get("payload") or {}
        turn_id = turn_meta.get("turn_id") or payload.get("turn_id")
        turn = self.turns.get(turn_id)
        if turn is None:
            return
        state = payload.get("state") or {
            "turn.started": "running",
            "turn.completed": "completed",
            "turn.failed": "failed",
            "turn.cancelled": "cancelled",
        }.get(event_type)
        if state in TERMINAL_TURN_STATES:
            self._finish_turn(turn, state, payload.get("error"))
        elif state:
            turn.state = state

    def _ingest_delivery(self, envelope: dict[str, Any]) -> None:
        payload = envelope.get("payload") or {}
        delivery = self.deliveries.get(payload.get("delivery_id"))
        if delivery is None:
            return
        state = payload.get("state")
        if state in ("done", "acked"):
            delivery.state = "done"
            delivery.lease_until = None
            delivery.error = None
            self.set_presence(delivery.agent_id, "online")
        elif state == "dead":
            self._retry_delivery(
                delivery, payload.get("error"), force_dead=True
            )
        elif state:
            self._retry_delivery(delivery, payload.get("error"))

    def _ingest_presence(self, payload: dict[str, Any]) -> None:
        agent_id = payload.get("agent_id")
        if agent_id is None:
            return
        self.set_presence(int(agent_id), payload.get("state", "offline"))

    # -- turn / delivery helpers ---------------------------------------

    def _schedule_turn(self, turn: Turn) -> None:
        active = self.active_turns.get(turn.thread_key)
        if active and active != turn.turn_id:
            self.backlog[turn.thread_key].append(turn.turn_id)
            return
        self.active_turns[turn.thread_key] = turn.turn_id
        turn.state = "queued"
        self._create_delivery(turn)

    def _create_delivery(self, turn: Turn) -> Delivery | None:
        for delivery in self.deliveries.values():
            if delivery.turn_id == turn.turn_id:
                return delivery
        kind = "command" if turn.command is not None else "message"
        payload = turn.command if kind == "command" else (turn.inbound or {})
        delivery = Delivery(
            delivery_id=new_id("dlv"),
            agent_id=turn.agent_id,
            turn_id=turn.turn_id,
            route=dict(turn.route),
            kind=kind,
            payload=payload,
        )
        self.deliveries[delivery.delivery_id] = delivery
        return delivery

    def _finish_turn(
        self, turn: Turn, state: str, error: str | None = None
    ) -> None:
        turn.state = state
        turn.finished_at = time.time()
        turn.error = error
        if self.active_turns.get(turn.thread_key) != turn.turn_id:
            return
        self.active_turns.pop(turn.thread_key, None)
        self._dispatch_next(turn.thread_key)

    def _dispatch_next(self, thread_key: str) -> None:
        backlog = self.backlog.get(thread_key)
        while backlog:
            turn_id = backlog.popleft()
            turn = self.turns.get(turn_id)
            if turn is None or turn.state != "queued":
                continue
            self.active_turns[thread_key] = turn.turn_id
            self._create_delivery(turn)
            return

    def _create_outbox(
        self,
        turn: Turn,
        route: dict[str, Any],
        message: dict[str, Any],
    ) -> None:
        key = (
            turn.turn_id,
            message.get("stream_id") or message.get("message_id") or "",
        )
        if key in self.outbox_keys:
            return
        self.outbox_keys.add(key)
        outbox = Outbox(
            outbox_id=new_id("out"),
            channel_id=int(route["channel_id"]),
            thread_key=turn.thread_key,
            turn_id=turn.turn_id,
            message=message,
        )
        self.outbox[outbox.outbox_id] = outbox

    # -- agent delivery -------------------------------------------------

    def get_delivery(self, delivery_id: str | None) -> Delivery | None:
        if not delivery_id:
            return None
        return self.deliveries.get(delivery_id)

    def get_turn(self, turn_id: str | None) -> Turn | None:
        if not turn_id:
            return None
        return self.turns.get(turn_id)

    def list_outbox(self) -> list[Outbox]:
        return sorted(self.outbox.values(), key=lambda item: item.created_at)

    def claim(
        self, agent_id: int, limit: int = 10, now: float | None = None
    ) -> list[Delivery]:
        now = time.time() if now is None else now
        self.expire_leases(now)
        candidates = [
            delivery
            for delivery in self.deliveries.values()
            if delivery.agent_id == int(agent_id) and delivery.state == "queued"
        ]
        candidates.sort(key=lambda delivery: delivery.created_at)
        claimed = []
        for delivery in candidates[: max(0, int(limit))]:
            delivery.state = "claimed"
            delivery.attempt += 1
            delivery.lease_until = now + self.lease_seconds
            claimed.append(delivery)
        if claimed:
            self.set_presence(int(agent_id), "busy")
        return claimed

    def ack(
        self,
        delivery_id: str,
        state: str = "done",
        error: str | None = None,
    ) -> Delivery | None:
        delivery = self.deliveries.get(delivery_id)
        if delivery is None:
            return None
        if state == "done":
            delivery.state = "done"
            delivery.lease_until = None
            delivery.error = None
            self.set_presence(delivery.agent_id, "online")
        else:
            self._retry_delivery(delivery, error or state)
        return delivery

    def _retry_delivery(
        self,
        delivery: Delivery,
        error: str | None = None,
        force_dead: bool = False,
    ) -> None:
        delivery.error = error
        delivery.lease_until = None
        if force_dead or delivery.attempt >= self.max_attempts:
            delivery.state = "dead"
        else:
            delivery.state = "queued"

    def expire_leases(self, now: float | None = None) -> int:
        now = time.time() if now is None else now
        expired = 0
        for delivery in self.deliveries.values():
            if (
                delivery.state in ("claimed", "running")
                and delivery.lease_until is not None
                and delivery.lease_until <= now
            ):
                self._retry_delivery(delivery, "lease expired")
                expired += 1
        for outbox in self.outbox.values():
            if (
                outbox.state == "sending"
                and outbox.lease_until is not None
                and outbox.lease_until <= now
            ):
                self._retry_outbox(outbox, "lease expired")
                expired += 1
        return expired

    # -- channel outbox -------------------------------------------------

    def claim_outbox(
        self, channel_id: int, limit: int = 10, now: float | None = None
    ) -> list[Outbox]:
        now = time.time() if now is None else now
        candidates = [
            outbox
            for outbox in self.outbox.values()
            if outbox.channel_id == int(channel_id) and outbox.state == "pending"
        ]
        candidates.sort(key=lambda outbox: outbox.created_at)
        claimed = []
        for outbox in candidates[: max(0, int(limit))]:
            outbox.state = "sending"
            outbox.attempt += 1
            outbox.lease_until = now + self.lease_seconds
            claimed.append(outbox)
        return claimed

    def ack_outbox(
        self,
        outbox_id: str,
        sent: bool = True,
        error: str | None = None,
    ) -> Outbox | None:
        outbox = self.outbox.get(outbox_id)
        if outbox is None:
            return None
        outbox.lease_until = None
        if sent:
            outbox.state = "sent"
            outbox.error = None
        else:
            self._retry_outbox(outbox, error or "send failed")
        return outbox

    def _retry_outbox(self, outbox: Outbox, error: str | None = None) -> None:
        outbox.error = error
        outbox.lease_until = None
        if outbox.attempt >= self.max_attempts:
            outbox.state = "dead"
        else:
            outbox.state = "pending"

    # -- record feed ----------------------------------------------------

    def record_events(
        self, cursor: int = 0, limit: int = 500
    ) -> tuple[list[dict[str, Any]], int]:
        cursor = max(0, int(cursor))
        limit = max(1, min(int(limit), 1000))
        events = self.events[cursor : cursor + limit]
        return events, cursor + len(events)

    def ack_record(self, cursor: int) -> int:
        self.record_cursor_acked = max(
            self.record_cursor_acked, max(0, int(cursor))
        )
        return self.record_cursor_acked

    # -- presence / observability --------------------------------------

    def set_presence(self, agent_id: int, state: str) -> None:
        self.presence[int(agent_id)] = {
            "agent_id": int(agent_id),
            "state": state,
            "last_seen": time.time(),
            "queue_depth": self.queue_depth(agent_id),
        }

    def get_presence(self, agent_id: int) -> dict[str, Any] | None:
        return self.presence.get(int(agent_id))

    def queue_depth(self, agent_id: int) -> int:
        return sum(
            1
            for delivery in self.deliveries.values()
            if delivery.agent_id == int(agent_id)
            and delivery.state in ("queued", "claimed", "running")
        )

    def agent_snapshot(self) -> list[dict[str, Any]]:
        return sorted(
            self.presence.values(), key=lambda item: item["agent_id"]
        )

    def stats(self) -> dict[str, int]:
        return {
            "agents_online": sum(
                1
                for presence in self.presence.values()
                if presence["state"] in ("online", "busy")
            ),
            "deliveries_queued": sum(
                1 for delivery in self.deliveries.values() if delivery.state == "queued"
            ),
            "outbox_pending": sum(
                1 for outbox in self.outbox.values() if outbox.state == "pending"
            ),
            "record_events_total": len(self.events),
        }
