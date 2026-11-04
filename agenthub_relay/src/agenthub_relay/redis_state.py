"""Redis-backed relay state: durable turns, deliveries, outbox, record feed.

Same public contract as :class:`agenthub_relay.state.RelayState`, but every
mutation is persisted so a relay restart does not lose accepted messages,
leased deliveries or the record cursor. The record feed is a Redis Stream
whose entry ids are ``<monotonic seq>-0``; Odoo's integer cursor maps
directly onto that sequence.
"""

from __future__ import annotations

import hashlib
import json
import time
import uuid
from typing import Any

from .state import (
    MESSAGE_EVENT_TYPES,
    TERMINAL_TURN_STATES,
    Delivery,
    Outbox,
    Turn,
    new_id,
)

_SCHEDULE_TURN = """
local active = redis.call('GET', KEYS[1])
if active and active ~= ARGV[1] then
  redis.call('RPUSH', KEYS[2], ARGV[1])
  return 0
end
redis.call('SET', KEYS[1], ARGV[1])
return 1
"""

_ACTIVATE_NEXT = """
if redis.call('GET', KEYS[1]) ~= ARGV[1] then
  return false
end
local nxt = redis.call('LPOP', KEYS[2])
if nxt then
  redis.call('SET', KEYS[1], nxt)
  return nxt
end
redis.call('DEL', KEYS[1])
return false
"""

_CLAIM_DELIVERY = """
local state = redis.call('HGET', KEYS[1], 'state')
if state ~= 'queued' then
  return 0
end
redis.call('HSET', KEYS[1], 'state', 'claimed', 'lease_until', ARGV[1],
           'error', '')
redis.call('HINCRBY', KEYS[1], 'attempt', 1)
return 1
"""

_CLAIM_OUTBOX = """
local state = redis.call('HGET', KEYS[1], 'state')
if state ~= 'pending' then
  return 0
end
redis.call('HSET', KEYS[1], 'state', 'sending', 'lease_until', ARGV[1],
           'error', '')
redis.call('HINCRBY', KEYS[1], 'attempt', 1)
return 1
"""


def _dump(value: Any) -> str:
    return json.dumps(value, separators=(",", ":"), sort_keys=True)


def _load(value: str | None, default: Any = None) -> Any:
    if not value:
        return default
    try:
        return json.loads(value)
    except (TypeError, ValueError):
        return default


class RedisRelayState:
    """Durable relay state backed by Redis."""

    def __init__(
        self,
        url: str = "redis://127.0.0.1:6379/0",
        lease_seconds: float = 60.0,
        max_attempts: int = 5,
        *,
        prefix: str = "agenthub:",
        client: Any = None,
        dedup_ttl_seconds: int = 7 * 24 * 3600,
        record_trim_margin: int = 10_000,
    ):
        if client is None:
            import redis

            client = redis.Redis.from_url(url, decode_responses=True)
        self.redis = client
        self.lease_seconds = lease_seconds
        self.max_attempts = max_attempts
        self.prefix = prefix
        self.dedup_ttl_seconds = dedup_ttl_seconds
        self.record_trim_margin = max(0, int(record_trim_margin))

    # -- key helpers ----------------------------------------------------

    def _k(self, *parts: str) -> str:
        return self.prefix + ":".join(parts)

    def _once(self, name: str) -> bool:
        return bool(
            self.redis.set(self._k(name), "1", nx=True, ex=self.dedup_ttl_seconds)
        )

    @property
    def _record_stream(self) -> str:
        return self._k("record:stream")

    # -- serialization --------------------------------------------------

    @staticmethod
    def _turn_fields(turn: Turn) -> dict[str, str]:
        return {
            "turn_id": turn.turn_id,
            "thread_key": turn.thread_key,
            "agent_id": str(turn.agent_id),
            "route": _dump(turn.route),
            "state": turn.state,
            "inbound": _dump(turn.inbound) if turn.inbound is not None else "",
            "command": _dump(turn.command) if turn.command is not None else "",
            "created_at": str(turn.created_at),
            "finished_at": "" if turn.finished_at is None else str(turn.finished_at),
            "error": turn.error or "",
        }

    @staticmethod
    def _delivery_fields(delivery: Delivery) -> dict[str, str]:
        return {
            "delivery_id": delivery.delivery_id,
            "agent_id": str(delivery.agent_id),
            "turn_id": delivery.turn_id,
            "route": _dump(delivery.route),
            "kind": delivery.kind,
            "payload": _dump(delivery.payload),
            "state": delivery.state,
            "attempt": str(delivery.attempt),
            "lease_until": ""
            if delivery.lease_until is None
            else str(delivery.lease_until),
            "error": delivery.error or "",
            "created_at": str(delivery.created_at),
        }

    @staticmethod
    def _outbox_fields(outbox: Outbox) -> dict[str, str]:
        return {
            "outbox_id": outbox.outbox_id,
            "channel_id": str(outbox.channel_id),
            "thread_key": outbox.thread_key,
            "turn_id": outbox.turn_id,
            "message": _dump(outbox.message),
            "state": outbox.state,
            "attempt": str(outbox.attempt),
            "lease_until": ""
            if outbox.lease_until is None
            else str(outbox.lease_until),
            "error": outbox.error or "",
            "created_at": str(outbox.created_at),
        }

    def _save_turn(self, turn: Turn) -> None:
        self.redis.hset(self._k("turn", turn.turn_id), mapping=self._turn_fields(turn))
        self.redis.sadd(self._k("turns:all"), turn.turn_id)

    def _save_delivery(self, delivery: Delivery) -> None:
        self.redis.hset(
            self._k("delivery", delivery.delivery_id),
            mapping=self._delivery_fields(delivery),
        )
        self.redis.sadd(self._k("deliveries:all"), delivery.delivery_id)

    def _save_outbox(self, outbox: Outbox) -> None:
        self.redis.hset(
            self._k("outbox", outbox.outbox_id),
            mapping=self._outbox_fields(outbox),
        )
        self.redis.sadd(self._k("outbox:all"), outbox.outbox_id)

    def get_turn(self, turn_id: str) -> Turn | None:
        data = self.redis.hgetall(self._k("turn", turn_id))
        if not data:
            return None
        return Turn(
            turn_id=data["turn_id"],
            thread_key=data.get("thread_key") or "",
            agent_id=int(data.get("agent_id") or 0),
            route=_load(data.get("route"), {}) or {},
            state=data.get("state") or "queued",
            inbound=_load(data.get("inbound")),
            command=_load(data.get("command")),
            created_at=float(data.get("created_at") or 0),
            finished_at=float(data["finished_at"])
            if data.get("finished_at")
            else None,
            error=data.get("error") or None,
        )

    def get_delivery(self, delivery_id: str | None) -> Delivery | None:
        if not delivery_id:
            return None
        data = self.redis.hgetall(self._k("delivery", delivery_id))
        if not data:
            return None
        return Delivery(
            delivery_id=data["delivery_id"],
            agent_id=int(data.get("agent_id") or 0),
            turn_id=data.get("turn_id") or "",
            route=_load(data.get("route"), {}) or {},
            kind=data.get("kind") or "message",
            payload=_load(data.get("payload"), {}) or {},
            state=data.get("state") or "queued",
            attempt=int(data.get("attempt") or 0),
            lease_until=float(data["lease_until"])
            if data.get("lease_until")
            else None,
            error=data.get("error") or None,
            created_at=float(data.get("created_at") or 0),
        )

    def get_outbox(self, outbox_id: str) -> Outbox | None:
        data = self.redis.hgetall(self._k("outbox", outbox_id))
        if not data:
            return None
        return Outbox(
            outbox_id=data["outbox_id"],
            channel_id=int(data.get("channel_id") or 0),
            thread_key=data.get("thread_key") or "",
            turn_id=data.get("turn_id") or "",
            message=_load(data.get("message"), {}) or {},
            state=data.get("state") or "pending",
            attempt=int(data.get("attempt") or 0),
            lease_until=float(data["lease_until"])
            if data.get("lease_until")
            else None,
            error=data.get("error") or None,
            created_at=float(data.get("created_at") or 0),
        )

    # -- ingest ---------------------------------------------------------

    def ingest(self, envelope: dict[str, Any]) -> str:
        event_id = envelope.get("event_id")
        if not event_id:
            raise ValueError("event_id is required")
        if not self._once(f"event:{event_id}"):
            return "duplicate"

        event_type = envelope.get("event_type")
        if event_type == "presence.changed":
            self._ingest_presence(envelope.get("payload") or {})
            return "accepted"

        if event_type in MESSAGE_EVENT_TYPES:
            raw_key = _dump(self._message_key(envelope))
            digest = hashlib.sha1(raw_key.encode("utf-8")).hexdigest()
            if not self._once(f"message:{digest}"):
                return "duplicate"
            self._append_record(envelope)
            return self._ingest_message(envelope)

        self._append_record(envelope)
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

    def _append_record(self, envelope: dict[str, Any]) -> int:
        seq = int(self.redis.incr(self._k("record:seq")))
        self.redis.xadd(
            self._record_stream,
            {"data": _dump(envelope)},
            id=f"{seq}-0",
        )
        return seq

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
        if self.get_turn(turn_id) is not None:
            return "duplicate"
        turn = Turn(
            turn_id=turn_id,
            thread_key=route["thread_key"],
            agent_id=int(route["agent_id"]),
            route=dict(route),
            inbound=message,
        )
        self._save_turn(turn)
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
        turn = self.get_turn(turn_id) if turn_id else None
        if turn is None:
            turn = Turn(
                turn_id=turn_id or new_id("turn"),
                thread_key=route.get("thread_key") or "",
                agent_id=int(route.get("agent_id") or 0),
                route=dict(route),
                state="running",
            )
        turn.state = "running"
        self._save_turn(turn)

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
        if self.get_turn(turn_id) is not None:
            return "duplicate"
        turn = Turn(
            turn_id=turn_id,
            thread_key=thread_key,
            agent_id=int(agent_id),
            route=dict(route),
            command=command,
        )
        self._save_turn(turn)
        self._schedule_turn(turn)
        return "accepted"

    def _ingest_turn(self, envelope: dict[str, Any]) -> None:
        event_type = envelope.get("event_type") or ""
        turn_meta = envelope.get("turn") or {}
        payload = envelope.get("payload") or {}
        turn_id = turn_meta.get("turn_id") or payload.get("turn_id")
        turn = self.get_turn(turn_id) if turn_id else None
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
            self._save_turn(turn)

    def _ingest_delivery(self, envelope: dict[str, Any]) -> None:
        payload = envelope.get("payload") or {}
        delivery = self.get_delivery(payload.get("delivery_id"))
        if delivery is None:
            return
        state = payload.get("state")
        if state in ("done", "acked"):
            self._mark_delivery_done(delivery)
        elif state == "dead":
            self._retry_delivery(delivery, payload.get("error"), force_dead=True)
        elif state:
            self._retry_delivery(delivery, payload.get("error"))

    def _ingest_presence(self, payload: dict[str, Any]) -> None:
        agent_id = payload.get("agent_id")
        if agent_id is None:
            return
        self.set_presence(int(agent_id), payload.get("state", "offline"))

    # -- turn / delivery helpers ---------------------------------------

    def _schedule_turn(self, turn: Turn) -> None:
        activated = self.redis.eval(
            _SCHEDULE_TURN,
            2,
            self._k("active", turn.thread_key),
            self._k("backlog", turn.thread_key),
            turn.turn_id,
        )
        if not int(activated):
            return
        turn.state = "queued"
        self._save_turn(turn)
        self._create_delivery(turn)

    def _create_delivery(self, turn: Turn) -> Delivery | None:
        slot = self._k("turn", turn.turn_id, "delivery")
        existing = self.redis.get(slot)
        if existing:
            return self.get_delivery(existing)
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
        self._save_delivery(delivery)
        if not self.redis.set(slot, delivery.delivery_id, nx=True):
            self.redis.delete(self._k("delivery", delivery.delivery_id))
            self.redis.srem(self._k("deliveries:all"), delivery.delivery_id)
            return self.get_delivery(self.redis.get(slot))
        self._enqueue_delivery(delivery)
        return delivery

    def _enqueue_delivery(self, delivery: Delivery) -> None:
        score = delivery.created_at
        self.redis.zadd(
            self._k("agent", str(delivery.agent_id), "pending"),
            {delivery.delivery_id: score},
        )
        self.redis.zadd(self._k("deliveries:pending"), {delivery.delivery_id: score})

    def _finish_turn(
        self, turn: Turn, state: str, error: str | None = None
    ) -> None:
        turn.state = state
        turn.finished_at = time.time()
        turn.error = error
        self._save_turn(turn)
        active_key = self._k("active", turn.thread_key)
        if self.redis.get(active_key) != turn.turn_id:
            return
        self._activate_next(turn.thread_key, turn.turn_id)

    def _activate_next(self, thread_key: str, expected: str) -> Turn | None:
        active_key = self._k("active", thread_key)
        backlog_key = self._k("backlog", thread_key)
        current = expected
        while True:
            next_id = self.redis.eval(
                _ACTIVATE_NEXT, 2, active_key, backlog_key, current
            )
            if not next_id:
                return None
            if isinstance(next_id, bytes):
                next_id = next_id.decode()
            turn = self.get_turn(next_id)
            if turn is not None and turn.state == "queued":
                self._create_delivery(turn)
                return turn
            current = next_id

    def _dispatch_next(self, thread_key: str) -> None:
        current = self.redis.get(self._k("active", thread_key))
        if current:
            self._activate_next(thread_key, current)

    def _create_outbox(
        self,
        turn: Turn,
        route: dict[str, Any],
        message: dict[str, Any],
    ) -> None:
        stream_or_message = message.get("stream_id") or message.get("message_id") or ""
        digest = hashlib.sha1(
            _dump([turn.turn_id, stream_or_message]).encode("utf-8")
        ).hexdigest()
        if not self._once(f"outboxkey:{digest}"):
            return
        outbox = Outbox(
            outbox_id=new_id("out"),
            channel_id=int(route["channel_id"]),
            thread_key=turn.thread_key,
            turn_id=turn.turn_id,
            message=message,
        )
        self._save_outbox(outbox)
        self.redis.zadd(
            self._k("channel", str(outbox.channel_id), "pending"),
            {outbox.outbox_id: outbox.created_at},
        )
        self.redis.zadd(
            self._k("outbox:pending"), {outbox.outbox_id: outbox.created_at}
        )

    # -- agent delivery -------------------------------------------------

    def claim(
        self, agent_id: int, limit: int = 10, now: float | None = None
    ) -> list[Delivery]:
        now = time.time() if now is None else now
        if int(limit) <= 0:
            return []
        self.expire_leases(now)
        pending = self._k("agent", str(int(agent_id)), "pending")
        inflight = self._k("agent", str(int(agent_id)), "inflight")
        candidates = self.redis.zrange(pending, 0, max(0, int(limit)) - 1)
        claimed: list[Delivery] = []
        for delivery_id in candidates:
            if not self.redis.eval(
                _CLAIM_DELIVERY,
                1,
                self._k("delivery", delivery_id),
                now + self.lease_seconds,
            ):
                self.redis.zrem(pending, delivery_id)
                self.redis.zrem(self._k("deliveries:pending"), delivery_id)
                continue
            delivery = self.get_delivery(delivery_id)
            if delivery is None:
                continue
            delivery.state = "claimed"
            delivery.lease_until = now + self.lease_seconds
            self.redis.zrem(pending, delivery_id)
            self.redis.zrem(self._k("deliveries:pending"), delivery_id)
            self.redis.zadd(inflight, {delivery_id: delivery.lease_until})
            self.redis.zadd(
                self._k("deliveries:inflight"),
                {delivery_id: delivery.lease_until},
            )
            self.redis.zadd(
                self._k("delivery:leases"),
                {delivery_id: delivery.lease_until},
            )
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
        delivery = self.get_delivery(delivery_id)
        if delivery is None:
            return None
        if state == "done":
            self._mark_delivery_done(delivery)
        else:
            self._retry_delivery(delivery, error or state)
        return delivery

    def _mark_delivery_done(self, delivery: Delivery) -> None:
        delivery.state = "done"
        delivery.lease_until = None
        delivery.error = None
        self._save_delivery(delivery)
        self._remove_delivery_leases(delivery)
        self.set_presence(delivery.agent_id, "online")

    def _remove_delivery_leases(self, delivery: Delivery) -> None:
        for key in (
            self._k("agent", str(delivery.agent_id), "inflight"),
            self._k("agent", str(delivery.agent_id), "pending"),
            self._k("deliveries:inflight"),
            self._k("deliveries:pending"),
            self._k("delivery:leases"),
        ):
            self.redis.zrem(key, delivery.delivery_id)

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
        self._save_delivery(delivery)
        self._remove_delivery_leases(delivery)
        if delivery.state == "queued":
            self._enqueue_delivery(delivery)

    def expire_leases(self, now: float | None = None) -> int:
        now = time.time() if now is None else now
        expired = 0
        for delivery_id in self.redis.zrangebyscore(
            self._k("delivery:leases"), "-inf", now
        ):
            delivery = self.get_delivery(delivery_id)
            if delivery is None:
                self.redis.zrem(self._k("delivery:leases"), delivery_id)
                continue
            if delivery.state not in ("claimed", "running"):
                self._remove_delivery_leases(delivery)
                continue
            if (delivery.lease_until or 0) > now:
                continue
            self._retry_delivery(delivery, "lease expired")
            expired += 1
        for outbox_id in self.redis.zrangebyscore(
            self._k("outbox:leases"), "-inf", now
        ):
            outbox = self.get_outbox(outbox_id)
            if outbox is None:
                self.redis.zrem(self._k("outbox:leases"), outbox_id)
                continue
            if outbox.state != "sending":
                self._remove_outbox_leases(outbox)
                continue
            if (outbox.lease_until or 0) > now:
                continue
            self._retry_outbox(outbox, "lease expired")
            expired += 1
        return expired

    # -- channel outbox -------------------------------------------------

    def claim_outbox(
        self, channel_id: int, limit: int = 10, now: float | None = None
    ) -> list[Outbox]:
        now = time.time() if now is None else now
        if int(limit) <= 0:
            return []
        pending = self._k("channel", str(int(channel_id)), "pending")
        candidates = self.redis.zrange(pending, 0, max(0, int(limit)) - 1)
        claimed: list[Outbox] = []
        for outbox_id in candidates:
            if not self.redis.eval(
                _CLAIM_OUTBOX,
                1,
                self._k("outbox", outbox_id),
                now + self.lease_seconds,
            ):
                self.redis.zrem(pending, outbox_id)
                self.redis.zrem(self._k("outbox:pending"), outbox_id)
                continue
            outbox = self.get_outbox(outbox_id)
            if outbox is None:
                continue
            outbox.state = "sending"
            outbox.lease_until = now + self.lease_seconds
            self.redis.zrem(pending, outbox_id)
            self.redis.zrem(self._k("outbox:pending"), outbox_id)
            self.redis.zadd(
                self._k("outbox:leases"), {outbox_id: outbox.lease_until}
            )
            claimed.append(outbox)
        return claimed

    def ack_outbox(
        self,
        outbox_id: str,
        sent: bool = True,
        error: str | None = None,
    ) -> Outbox | None:
        outbox = self.get_outbox(outbox_id)
        if outbox is None:
            return None
        if sent:
            outbox.state = "sent"
            outbox.lease_until = None
            outbox.error = None
            self._save_outbox(outbox)
            self._remove_outbox_leases(outbox)
        else:
            self._retry_outbox(outbox, error or "send failed")
        return outbox

    def _remove_outbox_leases(self, outbox: Outbox) -> None:
        for key in (
            self._k("channel", str(outbox.channel_id), "pending"),
            self._k("outbox:pending"),
            self._k("outbox:leases"),
        ):
            self.redis.zrem(key, outbox.outbox_id)

    def _retry_outbox(self, outbox: Outbox, error: str | None = None) -> None:
        outbox.error = error
        outbox.lease_until = None
        if outbox.attempt >= self.max_attempts:
            outbox.state = "dead"
        else:
            outbox.state = "pending"
        self._save_outbox(outbox)
        self._remove_outbox_leases(outbox)
        if outbox.state == "pending":
            self.redis.zadd(
                self._k("channel", str(outbox.channel_id), "pending"),
                {outbox.outbox_id: outbox.created_at},
            )
            self.redis.zadd(
                self._k("outbox:pending"), {outbox.outbox_id: outbox.created_at}
            )

    # -- record feed ----------------------------------------------------

    def record_events(
        self, cursor: int = 0, limit: int = 500
    ) -> tuple[list[dict[str, Any]], int]:
        cursor = max(0, int(cursor))
        limit = max(1, min(int(limit), 1000))
        entries = self.redis.xrange(
            self._record_stream,
            min=f"({cursor}-0",
            max="+",
            count=limit,
        )
        events: list[dict[str, Any]] = []
        next_cursor = cursor
        for entry_id, fields in entries:
            seq = int(entry_id.split("-", 1)[0])
            data = _load(fields.get("data"))
            if data is not None:
                events.append(data)
                next_cursor = max(next_cursor, seq)
        return events, next_cursor

    def ack_record(self, cursor: int) -> int:
        cursor = max(0, int(cursor))
        key = self._k("record:acked")
        previous = int(self.redis.get(key) or 0)
        acked = max(previous, cursor)
        self.redis.set(key, acked)
        if acked > self.record_trim_margin:
            # Keep a margin of already-acked entries: Odoo acks inside its
            # cron transaction, which may still roll back after the ack.
            self.redis.xtrim(
                self._record_stream,
                minid=f"{acked - self.record_trim_margin + 1}-0",
                approximate=False,
            )
        return acked

    def record_total(self) -> int:
        return int(self.redis.xlen(self._record_stream))

    # -- presence / observability --------------------------------------

    def set_presence(self, agent_id: int, state: str) -> None:
        agent_id = int(agent_id)
        self.redis.hset(
            self._k("presence", str(agent_id)),
            mapping={
                "agent_id": str(agent_id),
                "state": state,
                "last_seen": str(time.time()),
                "queue_depth": str(self.queue_depth(agent_id)),
            },
        )
        self.redis.sadd(self._k("presence:agents"), str(agent_id))

    def get_presence(self, agent_id: int) -> dict[str, Any] | None:
        data = self.redis.hgetall(self._k("presence", str(int(agent_id))))
        if not data:
            return None
        return {
            "agent_id": int(data["agent_id"]),
            "state": data.get("state", "offline"),
            "last_seen": float(data.get("last_seen") or 0),
            "queue_depth": int(data.get("queue_depth") or 0),
        }

    def queue_depth(self, agent_id: int) -> int:
        agent_id = int(agent_id)
        return int(
            self.redis.zcard(self._k("agent", str(agent_id), "pending"))
            + self.redis.zcard(self._k("agent", str(agent_id), "inflight"))
        )

    def agent_snapshot(self) -> list[dict[str, Any]]:
        agents = [
            self.get_presence(int(agent_id))
            for agent_id in self.redis.smembers(self._k("presence:agents"))
        ]
        return sorted(
            (agent for agent in agents if agent is not None),
            key=lambda item: item["agent_id"],
        )

    def stats(self) -> dict[str, int]:
        online = 0
        for agent_id in self.redis.smembers(self._k("presence:agents")):
            state = self.redis.hget(self._k("presence", agent_id), "state")
            if state in ("online", "busy"):
                online += 1
        return {
            "agents_online": online,
            "deliveries_queued": int(self.redis.zcard(self._k("deliveries:pending"))),
            "outbox_pending": int(self.redis.zcard(self._k("outbox:pending"))),
            "record_events_total": self.record_total(),
        }

    # -- test/introspection helpers ------------------------------------

    def active_turn(self, thread_key: str) -> str | None:
        return self.redis.get(self._k("active", thread_key))

    def backlog_ids(self, thread_key: str) -> list[str]:
        return list(self.redis.lrange(self._k("backlog", thread_key), 0, -1))

    def list_deliveries(self, agent_id: int | None = None) -> list[Delivery]:
        ids = self.redis.smembers(self._k("deliveries:all"))
        deliveries = [self.get_delivery(delivery_id) for delivery_id in ids]
        result = [
            delivery
            for delivery in deliveries
            if delivery is not None
            and (agent_id is None or delivery.agent_id == int(agent_id))
        ]
        return sorted(result, key=lambda item: item.created_at)

    def list_outbox(self) -> list[Outbox]:
        ids = self.redis.smembers(self._k("outbox:all"))
        outboxes = [self.get_outbox(outbox_id) for outbox_id in ids]
        return sorted(
            (outbox for outbox in outboxes if outbox is not None),
            key=lambda item: item.created_at,
        )
