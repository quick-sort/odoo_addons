"""WeCom aibot channel gateway: bot WebSocket server plus outbox sender.

One WebSocket per bot. A Redis lease guarantees only one relay instance owns a
given ``channel_id``; a second subscription from another instance is rejected
instead of kicking the live connection. Within one process a re-subscribe from
the same bot replaces the old socket (the legacy mutual-kick behaviour).

Outbound messages come from ``channel.<id>.outbox``; each sent callback records
a ``req_id -> route`` mapping so the bot's reply can be correlated back to its
turn. Replies are ingested as ``meta.origin=channel`` messages, which the state
store records but does not re-queue (no echo loop).
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
from typing import Any

from starlette.websockets import WebSocket, WebSocketDisconnect

from . import wecom
from .config import ChannelConfig, ConfigSnapshot, Settings
from .envelope import dump_envelope, parse_envelope
from .state import new_id

log = logging.getLogger(__name__)


class WecomConnection:
    def __init__(self, websocket: WebSocket, channel: ChannelConfig):
        self.websocket = websocket
        self.channel = channel
        self.lease_owner = uuid.uuid4().hex
        self.closed = False

    async def send(self, frame: dict[str, Any]) -> None:
        if self.closed:
            return
        await self.websocket.send_json(frame)

    async def kick(self) -> None:
        if self.closed:
            return
        self.closed = True
        try:
            await self.websocket.send_json(
                wecom.build_disconnected_event(
                    f"kick-{self.channel.bot_id}", self.channel.bot_id
                )
            )
        except Exception:  # noqa: BLE001 - socket already gone
            pass
        try:
            await self.websocket.close(code=4000)
        except Exception:  # noqa: BLE001 - socket already gone
            pass


class WecomGateway:
    def __init__(
        self,
        relay: Any,
        snapshot: ConfigSnapshot,
        settings: Settings,
        *,
        lease: Any = None,
        requests: Any = None,
    ):
        self.relay = relay
        self.snapshot = snapshot
        self.settings = settings
        self.lease = lease or wecom.make_lease(relay)
        self.requests = requests or wecom.make_request_map(relay)
        self.connections: dict[int, WecomConnection] = {}

    # -- connection lifecycle ------------------------------------------

    async def handle_ws(self, websocket: WebSocket) -> None:
        await websocket.accept()
        try:
            frame = await websocket.receive_json()
        except (WebSocketDisconnect, json.JSONDecodeError):
            await websocket.close(code=4001)
            return
        if frame.get("cmd") != wecom.CMD_SUBSCRIBE:
            await websocket.send_json(
                wecom.ack(
                    _req_id(frame),
                    errcode=wecom.AUTH_FAILED_ERRCODE,
                    errmsg="subscribe required",
                )
            )
            await websocket.close(code=4001)
            return

        req_id = _req_id(frame)
        body = frame.get("body") or {}
        channel = self.snapshot.find_channel(str(body.get("bot_id") or ""))
        if channel is None or channel.type != "wecom":
            await websocket.send_json(
                wecom.ack(
                    req_id,
                    errcode=wecom.AUTH_FAILED_ERRCODE,
                    errmsg="unknown bot",
                )
            )
            await websocket.close(code=4001)
            return
        if not channel.secret or body.get("secret") != channel.secret:
            await websocket.send_json(
                wecom.ack(
                    req_id,
                    errcode=wecom.AUTH_FAILED_ERRCODE,
                    errmsg="invalid secret",
                )
            )
            await websocket.close(code=4001)
            return

        lease_key = self._lease_key(channel.channel_id)
        existing = self.connections.get(channel.channel_id)
        if existing is not None:
            await existing.kick()
            self.lease.release(lease_key, existing.lease_owner)
            self.connections.pop(channel.channel_id, None)

        connection = WecomConnection(websocket, channel)
        if not self.lease.acquire(
            lease_key, connection.lease_owner, self.settings.wecom_lease_seconds
        ):
            await websocket.send_json(
                wecom.ack(
                    req_id,
                    errcode=wecom.LEASE_BUSY_ERRCODE,
                    errmsg="bot already connected elsewhere",
                )
            )
            await websocket.close(code=4003)
            return

        self.connections[channel.channel_id] = connection
        await websocket.send_json(wecom.ack(req_id))

        try:
            while True:
                frame = await websocket.receive_json()
                await self._handle_frame(connection, frame)
        except (WebSocketDisconnect, json.JSONDecodeError):
            pass
        except Exception:  # noqa: BLE001 - per-connection boundary
            log.exception("wecom gateway: connection error")
        finally:
            connection.closed = True
            if self.connections.get(channel.channel_id) is connection:
                self.connections.pop(channel.channel_id, None)
                self.lease.release(lease_key, connection.lease_owner)

    def _lease_key(self, channel_id: int) -> str:
        return f"lease:channel:{channel_id}"

    # -- inbound frames ------------------------------------------------

    async def _handle_frame(
        self, connection: WecomConnection, frame: dict[str, Any]
    ) -> None:
        cmd = frame.get("cmd")
        if cmd == wecom.CMD_PING:
            await connection.send(wecom.ping_response(frame))
            self.lease.renew(
                self._lease_key(connection.channel.channel_id),
                connection.lease_owner,
                self.settings.wecom_lease_seconds,
            )
            return
        if cmd in (wecom.CMD_RESPOND, wecom.CMD_SEND):
            await connection.send(wecom.acknowledge(frame))
            self._ingest_inbound(connection, frame)
            return
        if cmd == wecom.CMD_SUBSCRIBE:
            await connection.send(wecom.ack(_req_id(frame)))
            return
        log.warning("wecom gateway: unknown cmd %r", cmd)

    def _ingest_inbound(
        self, connection: WecomConnection, frame: dict[str, Any]
    ) -> str | None:
        fields = wecom.extract_inbound(frame)
        req_id = fields["reply_to_external_id"]
        if not req_id:
            log.warning("wecom gateway: reply without req_id")
            return None
        route = self.requests.get(req_id)
        if not route:
            log.warning("wecom gateway: unknown req_id %s", req_id)
            return None

        thread_key = route.get("thread_key") or ""
        agent_id = route.get("agent_id")
        if not thread_key or agent_id is None:
            log.warning("wecom gateway: incomplete route for req_id %s", req_id)
            return None

        msgtype = fields["msgtype"]
        stream_id = fields["stream_id"]
        if msgtype == "stream" or stream_id:
            final = fields["finished"]
            stream_key = stream_id or req_id
            event_type = "message.final" if final else "message.updated"
        else:
            # A plain text reply is complete even though it carries no stream
            # header; give it a synthetic stream id so the envelope validates.
            final = True
            stream_key = fields["external_id"] or req_id
            event_type = "message.final"

        ttl = self.settings.wecom_request_ttl_seconds
        seq = fields["seq"] or self.requests.next_seq(
            f"{req_id}:{stream_key}", ttl
        )
        channel_id = route.get("channel_id")
        event_id = (
            f"wecom:{channel_id}:{req_id}:{stream_key}:{seq}:{event_type}"
        )
        data = {
            "event_version": 1,
            "event_id": event_id,
            "event_type": event_type,
            "source": {"type": "agent", "id": str(agent_id)},
            "route": {
                "agent_id": agent_id,
                "channel_id": channel_id,
                "thread_key": thread_key,
                "peer_ref": route.get("peer_ref")
                or wecom.peer_ref_from_thread_key(thread_key),
            },
            "turn": {
                "turn_id": route.get("turn_id") or new_id("turn"),
                "seq": seq,
            },
            "payload": {
                "message_id": fields["external_id"]
                or fields["msgid"]
                or req_id,
                "role": "assistant",
                "content": fields["text"],
                "stream_id": stream_key,
                "seq": seq,
                "final": final,
                "author": {"type": "agent", "id": agent_id},
                "external_id": fields["external_id"] or None,
                "reply_to_external_id": req_id,
            },
            "meta": {"origin": "channel"},
        }
        return self.relay.ingest(dump_envelope(parse_envelope(data)))

    # -- outbound outbox -----------------------------------------------

    async def drain_outbox(self) -> int:
        sent = 0
        for channel_id, connection in list(self.connections.items()):
            if connection.closed:
                continue
            for outbox in self.relay.claim_outbox(channel_id, limit=10):
                frame, route = self._build_outbound(connection, outbox)
                self.requests.put(
                    outbox.outbox_id,
                    route,
                    self.settings.wecom_request_ttl_seconds,
                )
                try:
                    await connection.send(frame)
                except Exception as exc:  # noqa: BLE001 - socket boundary
                    self.relay.ack_outbox(
                        outbox.outbox_id, sent=False, error=str(exc)
                    )
                    await connection.kick()
                    self.connections.pop(channel_id, None)
                    self.lease.release(
                        self._lease_key(channel_id), connection.lease_owner
                    )
                    break
                self.relay.ack_outbox(outbox.outbox_id, sent=True)
                sent += 1
        return sent

    def _build_outbound(
        self, connection: WecomConnection, outbox: Any
    ) -> tuple[dict[str, Any], dict[str, Any]]:
        turn = self.relay.get_turn(outbox.turn_id)
        route = dict(turn.route) if turn is not None else {}
        peer_ref = (
            route.get("peer_ref")
            or wecom.peer_ref_from_thread_key(outbox.thread_key)
            or connection.channel.bot_id
        )
        agent_id = (
            turn.agent_id
            if turn is not None
            else wecom.agent_id_from_thread_key(outbox.thread_key)
        )
        frame = wecom.build_message_callback(
            msgid=outbox.outbox_id,
            aibotid=connection.channel.bot_id,
            chattype="single",
            userid=peer_ref,
            text=(outbox.message or {}).get("content") or "",
        )
        mapping = {
            "thread_key": outbox.thread_key,
            "agent_id": agent_id,
            "channel_id": outbox.channel_id,
            "turn_id": outbox.turn_id,
            "peer_ref": peer_ref,
        }
        return frame, mapping

    # -- background loop ------------------------------------------------

    def renew_leases(self) -> int:
        renewed = 0
        for channel_id, connection in list(self.connections.items()):
            if connection.closed:
                continue
            if self.lease.renew(
                self._lease_key(channel_id),
                connection.lease_owner,
                self.settings.wecom_lease_seconds,
            ):
                renewed += 1
            else:
                log.warning(
                    "wecom gateway: lost lease for channel %s", channel_id
                )
                self.connections.pop(channel_id, None)
                try:
                    asyncio.get_running_loop().create_task(
                        connection.kick()
                    )
                except RuntimeError:
                    connection.closed = True
        return renewed

    async def run(self) -> None:
        while True:
            try:
                self.renew_leases()
                await self.drain_outbox()
            except asyncio.CancelledError:
                raise
            except Exception:  # noqa: BLE001 - keep the loop alive
                log.exception("wecom gateway loop failed")
            await asyncio.sleep(self.settings.wecom_poll_seconds)


def _req_id(frame: dict[str, Any]) -> str:
    return str((frame.get("headers") or {}).get("req_id") or "")
