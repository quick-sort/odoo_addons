"""WeCom aibot WebSocket endpoint (gevent worker only).

This is the HTTP→WebSocket upgrade + connection loop. Odoo disables WebSockets
during unit tests (``WebsocketConnectionHandler.websocket_allowed`` returns
False under ``--test-enable``), so the loop here is verified manually against a
real OpenClaw client, not by the test suite. The frame handling it delegates to
is fully unit-tested in ``services/aibot.py``.
"""

import logging

from odoo import http
from odoo.http import request

from odoo.addons.bus.websocket import Websocket, WebsocketConnectionHandler

from ..services import aibot

_logger = logging.getLogger(__name__)


class WecomAibotController(http.Controller):
    @http.route(
        "/wecom/aibot/ws", type="http", auth="public", cors="*", websocket=True
    )
    def ws(self, **kwargs):
        return _open_connection(request)


def _open_connection(request):
    response = WebsocketConnectionHandler._get_handshake_response(
        request.httprequest.headers
    )
    socket = request.httprequest._HTTPRequest__environ["socket"]
    websocket = Websocket(socket, request.session, request.httprequest.cookies)
    response.call_on_close(lambda: _serve_forever(websocket, request))
    request.session.is_dirty = True
    return response


def _serve_forever(websocket, request):
    for raw in websocket.get_messages():
        if raw == b"\x00":
            continue
        try:
            frame = aibot.decode(raw)
        except (TypeError, ValueError):
            _logger.warning("agenthub_wecom: unparseable frame: %.200r", raw)
            continue
        response = _handle_frame(websocket, frame, request)
        if response is not None:
            websocket._send(aibot.encode(response))


def _handle_frame(websocket, frame, request):
    cmd = frame.get("cmd")
    if cmd == aibot.CMD_SUBSCRIBE:
        return _handle_subscribe(websocket, frame, request)
    if cmd == aibot.CMD_PING:
        return aibot.ping_response(frame)
    if cmd in (aibot.CMD_RESPOND, aibot.CMD_SEND):
        _handle_inbound(frame, request)
        return aibot.acknowledge(frame)
    return None


def _handle_subscribe(websocket, frame, request):
    req_id = frame["headers"]["req_id"]
    body = frame.get("body", {})
    bot_id = body.get("bot_id", "")
    channel = request.env["agenthub.channel"].search(
        [("channel_type", "=", "wecom"), ("bot_id", "=", bot_id)], limit=1
    )
    if not channel:
        return aibot.ack(
            req_id, errcode=aibot.AUTH_FAILED_ERRCODE, errmsg="unknown bot"
        )
    if body.get("secret") != channel.secret:
        return aibot.ack(
            req_id, errcode=aibot.AUTH_FAILED_ERRCODE, errmsg="invalid secret"
        )
    aibot.registry.register(bot_id, _SocketConnection(websocket, bot_id))
    return aibot.ack(req_id)


def _handle_inbound(frame, request):
    """Persist an inbound respond/send frame as an inbound mail.message.

    Stream accumulation (many frames, one message) is the agent's concern; here
    each frame is recorded with its correlation ids so the agent can reassemble
    it. A fuller implementation folds frames sharing ``agenthub_stream_id`` into
    one message.
    """
    fields_ = aibot.extract_inbound(frame)
    request.env["mail.message"].create(
        {
            "body": fields_["text"],
            "agenthub_role": "assistant",
            "agenthub_direction": "in",
            "agenthub_external_id": fields_["external_id"],
            "agenthub_reply_to_external_id": fields_["reply_to_external_id"],
        }
    )


class _SocketConnection:
    """Adapts a bus ``Websocket`` to the registry's send/kick protocol."""

    def __init__(self, websocket, bot_id):
        self.websocket = websocket
        self.bot_id = bot_id

    def send(self, frame):
        self.websocket._send(aibot.encode(frame))

    def kick(self):
        self.send(
            aibot.build_disconnected_event("kick-%s" % self.bot_id, self.bot_id)
        )
