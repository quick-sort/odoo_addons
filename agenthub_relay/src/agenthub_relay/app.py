"""Starlette app for the relay v1 skeleton."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import time
from contextlib import asynccontextmanager
from typing import Any

import uvicorn
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Route, WebSocketRoute
from starlette.websockets import WebSocket, WebSocketDisconnect

from .config import ConfigSnapshot, Settings, load_snapshot
from .config_sync import config_sync_loop
from .envelope import dump_envelope, parse_envelope
from .gateway import WecomGateway
from .protocol import (
    AgentDirectory,
    authenticate_agent,
    build_error,
    build_stream_envelope,
    build_turn_envelope,
)
from .router import Router
from .state import RelayState


def sign_body(secret: str, body: bytes, timestamp: str) -> str:
    return hmac.new(
        secret.encode("utf-8"),
        f"{timestamp}.".encode("utf-8") + body,
        hashlib.sha256,
    ).hexdigest()


def verify_signature(
    headers: Any, body: bytes, settings: Settings
) -> bool:
    timestamp = headers.get("x-agenthub-timestamp")
    signature = headers.get("x-agenthub-signature")
    if not timestamp or not signature:
        return False
    try:
        issued_at = int(timestamp)
    except (TypeError, ValueError):
        return False
    if abs(time.time() - issued_at) > settings.timestamp_window:
        return False
    expected = sign_body(settings.publish_secret, body, timestamp)
    return hmac.compare_digest(expected, signature)


async def health(request: Request) -> JSONResponse:
    return JSONResponse({"status": "ok"})


async def metrics(request: Request) -> PlainTextResponse:
    stats = request.app.state.relay.stats()
    lines = [
        "# TYPE agenthub_agents_online gauge",
        f"agenthub_agents_online {stats['agents_online']}",
        "# TYPE agenthub_deliveries_queued gauge",
        f"agenthub_deliveries_queued {stats['deliveries_queued']}",
        "# TYPE agenthub_outbox_pending gauge",
        f"agenthub_outbox_pending {stats['outbox_pending']}",
        "# TYPE agenthub_record_events_total gauge",
        f"agenthub_record_events_total {stats['record_events_total']}",
    ]
    return PlainTextResponse("\n".join(lines) + "\n")


async def publish(request: Request) -> JSONResponse:
    settings: Settings = request.app.state.settings
    body = await request.body()
    if not verify_signature(request.headers, body, settings):
        return JSONResponse({"error": "invalid signature"}, status_code=401)
    try:
        data = json.loads(body)
        envelope = parse_envelope(data)
    except Exception as exc:  # noqa: BLE001 - validation boundary
        return JSONResponse({"error": str(exc)}, status_code=400)
    status = request.app.state.relay.ingest(dump_envelope(envelope))
    return JSONResponse({"status": status, "event_id": envelope.event_id})


def _recorder_authorized(request: Request) -> bool:
    settings: Settings = request.app.state.settings
    token = request.headers.get("x-agenthub-recorder-token", "")
    return bool(token) and hmac.compare_digest(token, settings.recorder_token)


async def record(request: Request) -> JSONResponse:
    if not _recorder_authorized(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    relay: RelayState = request.app.state.relay
    cursor = int(request.query_params.get("cursor", "0") or 0)
    limit = int(request.query_params.get("limit", "500") or 500)
    events, next_cursor = relay.record_events(cursor, limit)
    return JSONResponse(
        {
            "events": events,
            "next_cursor": next_cursor,
            "lag_seconds": 0.0,
        }
    )


async def record_ack(request: Request) -> JSONResponse:
    if not _recorder_authorized(request):
        return JSONResponse({"error": "unauthorized"}, status_code=401)
    relay: RelayState = request.app.state.relay
    data = await request.json()
    cursor = relay.ack_record(int(data.get("cursor", 0)))
    return JSONResponse({"status": "ok", "cursor": cursor})


async def agents(request: Request) -> JSONResponse:
    return JSONResponse({"agents": request.app.state.relay.agent_snapshot()})


async def _deliver_loop(
    websocket: WebSocket, relay: RelayState, agent_id: int
) -> None:
    try:
        while True:
            deliveries = relay.claim(agent_id, limit=4)
            for delivery in deliveries:
                await websocket.send_json(delivery.deliver_frame())
            await asyncio.sleep(0.5)
    except (WebSocketDisconnect, RuntimeError, asyncio.CancelledError):
        return


async def _handle_agent_frame(
    websocket: WebSocket,
    relay: RelayState,
    agent_id: int,
    frame: dict[str, Any],
) -> None:
    frame_type = frame.get("type")
    if frame_type == "ping":
        await websocket.send_json({"type": "pong"})
        return

    delivery_id = frame.get("delivery_id")
    delivery = relay.get_delivery(delivery_id)
    if delivery is None or delivery.agent_id != agent_id:
        await websocket.send_json(
            build_error("TURN_NOT_FOUND", "unknown delivery")
        )
        return

    if frame_type == "stream":
        envelope = build_stream_envelope(delivery, frame)
        relay.ingest(envelope)
        await websocket.send_json(
            {
                "type": "ack",
                "delivery_id": delivery_id,
                "event_id": envelope["event_id"],
            }
        )
        return

    if frame_type == "turn":
        envelope = build_turn_envelope(
            delivery,
            frame.get("state", "completed"),
            frame.get("error"),
        )
        relay.ingest(envelope)
        await websocket.send_json(
            {
                "type": "ack",
                "delivery_id": delivery_id,
                "event_id": envelope["event_id"],
            }
        )
        return

    if frame_type == "ack":
        relay.ack(
            delivery_id,
            state=frame.get("state", "done"),
            error=frame.get("error"),
        )
        await websocket.send_json(
            {"type": "ack", "delivery_id": delivery_id}
        )
        return

    await websocket.send_json(
        build_error("INVALID_ENVELOPE", f"unknown frame type {frame_type!r}")
    )


async def channel_wecom_ws(websocket: WebSocket) -> None:
    gateway: WecomGateway = websocket.app.state.wecom
    await gateway.handle_ws(websocket)


async def agent_ws(websocket: WebSocket) -> None:
    relay: RelayState = websocket.app.state.relay
    directory: AgentDirectory = websocket.app.state.directory
    await websocket.accept()
    try:
        auth = await websocket.receive_json()
    except (WebSocketDisconnect, json.JSONDecodeError):
        await websocket.close(code=4001)
        return
    agent_id = authenticate_agent(directory, auth)
    if agent_id is None:
        await websocket.send_json(build_error("AUTH_FAILED", "invalid token"))
        await websocket.close(code=4001)
        return

    relay.set_presence(agent_id, "online")
    await websocket.send_json(
        {
            "type": "hello",
            "heartbeat_sec": 20,
            "limits": {"max_inflight": 4, "max_payload_bytes": 1048576},
        }
    )
    sender = asyncio.create_task(_deliver_loop(websocket, relay, agent_id))
    try:
        while True:
            frame = await websocket.receive_json()
            try:
                await _handle_agent_frame(
                    websocket, relay, agent_id, frame
                )
            except Exception as exc:  # noqa: BLE001 - protocol boundary
                await websocket.send_json(
                    build_error("INVALID_ENVELOPE", str(exc))
                )
    except (WebSocketDisconnect, json.JSONDecodeError):
        pass
    finally:
        sender.cancel()
        relay.set_presence(agent_id, "offline")


def create_app(
    settings: Settings | None = None,
    snapshot: ConfigSnapshot | None = None,
    relay: RelayState | None = None,
    gateway: WecomGateway | None = None,
) -> Starlette:
    settings = settings or Settings.from_env()
    snapshot = snapshot or ConfigSnapshot()
    if relay is None:
        if settings.redis_url:
            from .redis_state import RedisRelayState

            relay = RedisRelayState(
                settings.redis_url,
                lease_seconds=settings.lease_seconds,
                max_attempts=settings.max_attempts,
            )
        else:
            relay = RelayState(
                lease_seconds=settings.lease_seconds,
                max_attempts=settings.max_attempts,
            )

    gateway = gateway or WecomGateway(relay, snapshot, settings)

    @asynccontextmanager
    async def lifespan(app):
        tasks = []
        if settings.odoo_config_url and settings.odoo_config_token:
            tasks.append(asyncio.create_task(config_sync_loop(app)))
        tasks.append(asyncio.create_task(gateway.run()))
        try:
            yield
        finally:
            for task in tasks:
                task.cancel()
            for task in tasks:
                try:
                    await task
                except asyncio.CancelledError:
                    pass

    app = Starlette(
        routes=[
            Route("/healthz", health),
            Route("/metrics", metrics),
            Route("/v1/publish", publish, methods=["POST"]),
            Route("/v1/record", record, methods=["GET"]),
            Route("/v1/record/ack", record_ack, methods=["POST"]),
            Route("/v1/admin/agents", agents, methods=["GET"]),
            WebSocketRoute("/v1/agent/ws", agent_ws),
            WebSocketRoute("/v1/channel/wecom/ws", channel_wecom_ws),
        ],
        lifespan=lifespan,
    )
    app.state.settings = settings
    app.state.snapshot = snapshot
    app.state.relay = relay
    app.state.wecom = gateway
    app.state.directory = AgentDirectory(snapshot.agents)
    app.state.router = Router(snapshot)
    return app


def main() -> None:
    settings = Settings.from_env()
    snapshot = (
        load_snapshot(settings.config_file)
        if settings.config_file
        else ConfigSnapshot()
    )
    app = create_app(settings=settings, snapshot=snapshot)
    uvicorn.run(app, host=settings.host, port=settings.port)


if __name__ == "__main__":
    main()
