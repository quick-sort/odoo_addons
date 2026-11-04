"""WeCom aibot WebSocket protocol and bot-lease helpers.

Frame helpers are pure functions (ported from ``agenthub_wecom``) so they can
be tested without a socket. ``MemoryLease`` / ``RedisLease`` implement the
single-owner bot lease; ``RequestMap`` correlates bot replies back to the
outbound callback that triggered them.
"""

from __future__ import annotations

import json
import time
import uuid
from typing import Any

CMD_SUBSCRIBE = "aibot_subscribe"
CMD_PING = "ping"
CMD_RESPOND = "aibot_respond_msg"
CMD_SEND = "aibot_send_msg"
CMD_CALLBACK = "aibot_msg_callback"
CMD_EVENT = "aibot_event_callback"

AUTH_FAILED_ERRCODE = 40001
LEASE_BUSY_ERRCODE = 40003

_RENEW_LEASE = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('PEXPIRE', KEYS[1], ARGV[2])
end
return 0
"""

_RELEASE_LEASE = """
if redis.call('GET', KEYS[1]) == ARGV[1] then
  return redis.call('DEL', KEYS[1])
end
return 0
"""


def encode(frame: dict[str, Any]) -> str:
    return json.dumps(frame, separators=(",", ":"))


def decode(raw: str | bytes) -> dict[str, Any]:
    return json.loads(raw)


def ack(req_id: str, errcode: int = 0, errmsg: str = "ok") -> dict[str, Any]:
    return {"headers": {"req_id": req_id}, "errcode": errcode, "errmsg": errmsg}


def authenticate(frame: dict[str, Any], secret: str) -> dict[str, Any]:
    req_id = (frame.get("headers") or {}).get("req_id", "")
    if not secret or (frame.get("body") or {}).get("secret") != secret:
        return ack(req_id, errcode=AUTH_FAILED_ERRCODE, errmsg="invalid secret")
    return ack(req_id)


def ping_response(frame: dict[str, Any]) -> dict[str, Any]:
    return ack((frame.get("headers") or {}).get("req_id", ""))


def acknowledge(frame: dict[str, Any]) -> dict[str, Any]:
    return ack((frame.get("headers") or {}).get("req_id", ""))


def build_message_callback(
    msgid: str,
    aibotid: str,
    chattype: str,
    userid: str,
    text: str,
    chatid: str | None = None,
) -> dict[str, Any]:
    body: dict[str, Any] = {
        "msgid": msgid,
        "aibotid": aibotid,
        "chattype": chattype,
        "from": {"userid": userid},
        "msgtype": "text",
        "text": {"content": text},
    }
    if chatid:
        body["chatid"] = chatid
    return {"cmd": CMD_CALLBACK, "headers": {"req_id": msgid}, "body": body}


def build_disconnected_event(msgid: str, aibotid: str) -> dict[str, Any]:
    return {
        "cmd": CMD_EVENT,
        "headers": {"req_id": msgid},
        "body": {
            "msgid": msgid,
            "aibotid": aibotid,
            "msgtype": "event",
            "event": {"eventtype": "disconnected_event"},
        },
    }


def extract_inbound(frame: dict[str, Any]) -> dict[str, Any]:
    """Normalise a bot ``respond``/``send`` frame into message fields."""
    body = frame.get("body") or {}
    req_id = (frame.get("headers") or {}).get("req_id", "")
    stream = body.get("stream") or {}
    external_id = stream.get("id") or body.get("msgid") or req_id
    return {
        "external_id": external_id,
        "reply_to_external_id": req_id,
        "text": _extract_text(body),
        "finished": bool(stream.get("finish")),
        "stream_id": stream.get("id"),
        "seq": int(stream.get("seq") or 0),
        "msgid": body.get("msgid") or "",
        "chatid": body.get("chatid") or "",
        "userid": (body.get("from") or {}).get("userid") or "",
        "msgtype": body.get("msgtype") or "",
    }


def _extract_text(body: dict[str, Any]) -> str:
    if body.get("msgtype") == "text":
        return (body.get("text") or {}).get("content", "")
    if body.get("msgtype") == "stream":
        return (body.get("stream") or {}).get("content", "")
    return ""


class MemoryLease:
    """Process-local lease store (tests / single instance without Redis)."""

    def __init__(self):
        self._leases: dict[str, tuple[str, float]] = {}

    def acquire(self, key: str, owner: str, ttl: float) -> bool:
        now = time.monotonic()
        current = self._leases.get(key)
        if current is not None and current[1] > now and current[0] != owner:
            return False
        self._leases[key] = (owner, now + ttl)
        return True

    def renew(self, key: str, owner: str, ttl: float) -> bool:
        now = time.monotonic()
        current = self._leases.get(key)
        if current is None or current[0] != owner or current[1] <= now:
            return False
        self._leases[key] = (owner, now + ttl)
        return True

    def release(self, key: str, owner: str) -> None:
        current = self._leases.get(key)
        if current is not None and current[0] == owner:
            del self._leases[key]

    def owner(self, key: str) -> str | None:
        current = self._leases.get(key)
        if current is None or current[1] <= time.monotonic():
            return None
        return current[0]


class RedisLease:
    """Single-owner lease backed by Redis ``SET NX PX``."""

    def __init__(self, client: Any, prefix: str = "agenthub:"):
        self.redis = client
        self.prefix = prefix

    def _key(self, key: str) -> str:
        return f"{self.prefix}{key}"

    @staticmethod
    def _ms(ttl: float) -> int:
        return max(1, int(ttl * 1000))

    def acquire(self, key: str, owner: str, ttl: float) -> bool:
        return bool(
            self.redis.set(self._key(key), owner, nx=True, px=self._ms(ttl))
        )

    def renew(self, key: str, owner: str, ttl: float) -> bool:
        return bool(
            self.redis.eval(
                _RENEW_LEASE, 1, self._key(key), owner, self._ms(ttl)
            )
        )

    def release(self, key: str, owner: str) -> None:
        self.redis.eval(_RELEASE_LEASE, 1, self._key(key), owner)

    def owner(self, key: str) -> str | None:
        return self.redis.get(self._key(key))


class MemoryRequestMap:
    def __init__(self):
        self._items: dict[str, tuple[float, dict[str, Any]]] = {}
        self._seq: dict[str, int] = {}

    def put(self, key: str, value: dict[str, Any], ttl: float) -> None:
        self._items[key] = (time.monotonic() + ttl, value)

    def get(self, key: str) -> dict[str, Any] | None:
        item = self._items.get(key)
        if item is None:
            return None
        if item[0] <= time.monotonic():
            self._items.pop(key, None)
            return None
        return item[1]

    def next_seq(self, key: str, ttl: float) -> int:
        self._seq[key] = self._seq.get(key, 0) + 1
        return self._seq[key]


class RedisRequestMap:
    def __init__(self, client: Any, prefix: str = "agenthub:"):
        self.redis = client
        self.prefix = prefix

    def _key(self, key: str) -> str:
        return f"{self.prefix}request:{key}"

    def put(self, key: str, value: dict[str, Any], ttl: float) -> None:
        self.redis.set(
            self._key(key),
            json.dumps(value, separators=(",", ":"), sort_keys=True),
            ex=max(1, int(ttl)),
        )

    def get(self, key: str) -> dict[str, Any] | None:
        raw = self.redis.get(self._key(key))
        if not raw:
            return None
        try:
            return json.loads(raw)
        except (TypeError, ValueError):
            return None

    def next_seq(self, key: str, ttl: float) -> int:
        redis_key = f"{self.prefix}seq:{key}"
        value = int(self.redis.incr(redis_key))
        self.redis.expire(redis_key, max(1, int(ttl)))
        return value


def make_lease(relay: Any) -> MemoryLease | RedisLease:
    client = getattr(relay, "redis", None)
    if client is None:
        return MemoryLease()
    return RedisLease(client, prefix=getattr(relay, "prefix", "agenthub:"))


def make_request_map(relay: Any) -> MemoryRequestMap | RedisRequestMap:
    client = getattr(relay, "redis", None)
    if client is None:
        return MemoryRequestMap()
    return RedisRequestMap(client, prefix=getattr(relay, "prefix", "agenthub:"))


def peer_ref_from_thread_key(thread_key: str) -> str:
    marker = ":peer:"
    if marker not in thread_key:
        return ""
    rest = thread_key.split(marker, 1)[1]
    return rest.split(":agent:", 1)[0]


def agent_id_from_thread_key(thread_key: str) -> int | None:
    marker = ":agent:"
    if marker not in thread_key:
        return None
    try:
        return int(thread_key.rsplit(marker, 1)[1])
    except (TypeError, ValueError):
        return None


def new_owner_id() -> str:
    return f"relay-{uuid.uuid4().hex}"
