"""aibot WebSocket protocol: frame building and command handling.

Pure functions with explicit inputs so the frame-level behaviour is testable
without a socket. ``ConnectionRegistry`` tracks live connections per bot_id and
implements the mutual-kick rule.

Command names follow ``@wecom/aibot-node-sdk`` (the plugin source's own
``aibot_callback`` / ``aibot_response`` constants are stale and unused).
"""

import json

CMD_SUBSCRIBE = "aibot_subscribe"
CMD_PING = "ping"
CMD_RESPOND = "aibot_respond_msg"
CMD_SEND = "aibot_send_msg"
CMD_CALLBACK = "aibot_msg_callback"
CMD_EVENT = "aibot_event_callback"

AUTH_FAILED_ERRCODE = 40001


def encode(frame):
    return json.dumps(frame)


def decode(raw):
    return json.loads(raw)


def ack(req_id, errcode=0, errmsg="ok"):
    return {"headers": {"req_id": req_id}, "errcode": errcode, "errmsg": errmsg}


def authenticate(frame, secret):
    """Validate a subscribe frame's secret and return the auth response."""
    req_id = frame["headers"]["req_id"]
    if not secret or frame.get("body", {}).get("secret") != secret:
        return ack(req_id, errcode=AUTH_FAILED_ERRCODE, errmsg="invalid secret")
    return ack(req_id)


def ping_response(frame):
    """Ack a heartbeat ping."""
    return ack(frame["headers"]["req_id"])


def acknowledge(frame):
    """Ack a respond/send command (the client waits for this ack)."""
    return ack(frame["headers"]["req_id"])


def build_message_callback(msgid, aibotid, chattype, userid, text, chatid=None):
    """Build an outbound ``aibot_msg_callback`` frame — a user message to the bot."""
    body = {
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


def build_disconnected_event(msgid, aibotid):
    """Build the event that tells an old connection it is being kicked."""
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


def extract_inbound(frame):
    """Normalise an inbound respond/send frame into mail.message field values.

    ``reply_to_external_id`` is the frame's ``req_id``: the SDK echoes the
    callback's ``req_id`` when replying, so it correlates the reply back to the
    outbound question (whose ``agenthub_external_id`` carries that same id).
    """
    body = frame.get("body", {})
    req_id = frame.get("headers", {}).get("req_id", "")
    stream = body.get("stream") or {}
    return {
        "external_id": stream.get("id") or body.get("msgid") or req_id,
        "reply_to_external_id": req_id,
        "text": _extract_text(body),
        "finished": bool(stream.get("finish")),
    }


def _extract_text(body):
    if body.get("msgtype") == "text":
        return (body.get("text") or {}).get("content", "")
    if body.get("msgtype") == "stream":
        return (body.get("stream") or {}).get("content", "")
    return ""


class ConnectionRegistry:
    """In-process registry of live bot connections, per gevent worker.

    A connection is any object exposing ``send(frame)`` and ``kick()``; tests
    inject a fake to exercise the mutual-kick rule without a socket.
    """

    def __init__(self):
        self._connections = {}

    def register(self, bot_id, connection):
        """Register ``connection`` for ``bot_id``, kicking any previous one."""
        previous = self._connections.pop(bot_id, None)
        if previous is not None:
            previous.kick()
        self._connections[bot_id] = connection

    def get(self, bot_id):
        return self._connections.get(bot_id)

    def unregister(self, bot_id, connection):
        if self._connections.get(bot_id) is connection:
            del self._connections[bot_id]


# The gevent worker's single shared registry. The HTTP/cron workers never touch
# it: outbound delivery reaches the gevent worker through the DB queue instead.
registry = ConnectionRegistry()
