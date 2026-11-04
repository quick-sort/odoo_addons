import asyncio

from starlette.testclient import TestClient

from agenthub_relay import wecom
from agenthub_relay.app import create_app
from agenthub_relay.config import ChannelConfig, ConfigSnapshot, Settings
from agenthub_relay.gateway import WecomConnection, WecomGateway
from agenthub_relay.state import RelayState

from .helpers import message_envelope


class FakeWebSocket:
    def __init__(self):
        self.sent = []
        self.closed = False

    async def send_json(self, frame):
        self.sent.append(frame)

    async def close(self, code=1000):
        self.closed = True


def channel_snapshot() -> ConfigSnapshot:
    return ConfigSnapshot.from_dict(
        {
            "channels": [
                {
                    "id": 10,
                    "type": "wecom",
                    "bot_id": "bot-1",
                    "secret": "s3cret",
                    "active": True,
                }
            ]
        }
    )


def test_authenticate_and_ping():
    frame = {"headers": {"req_id": "sub-1"}, "body": {"secret": "ok"}}
    assert wecom.authenticate(frame, "ok")["errcode"] == 0
    failed = wecom.authenticate(
        {"headers": {"req_id": "sub-2"}, "body": {"secret": "bad"}}, "ok"
    )
    assert failed["errcode"] == wecom.AUTH_FAILED_ERRCODE
    assert failed["headers"]["req_id"] == "sub-2"
    ping = wecom.ping_response({"headers": {"req_id": "ping-1"}})
    assert ping == {"headers": {"req_id": "ping-1"}, "errcode": 0, "errmsg": "ok"}


def test_extract_text_and_stream():
    text = wecom.extract_inbound(
        {
            "headers": {"req_id": "r1"},
            "body": {"msgtype": "text", "text": {"content": "hi"}},
        }
    )
    assert text["text"] == "hi"
    assert text["finished"] is False
    assert text["external_id"] == "r1"

    stream = wecom.extract_inbound(
        {
            "headers": {"req_id": "r2"},
            "body": {
                "msgtype": "stream",
                "stream": {"id": "st-1", "finish": True, "content": "done", "seq": 3},
            },
        }
    )
    assert stream["stream_id"] == "st-1"
    assert stream["external_id"] == "st-1"
    assert stream["finished"] is True
    assert stream["seq"] == 3


def test_build_message_callback_carries_req_id():
    frame = wecom.build_message_callback(
        msgid="out-1", aibotid="bot-1", chattype="single", userid="u1", text="hello"
    )
    assert frame["cmd"] == wecom.CMD_CALLBACK
    assert frame["headers"]["req_id"] == "out-1"
    assert frame["body"]["from"]["userid"] == "u1"


def test_memory_lease_is_single_owner_and_expires():
    lease = wecom.MemoryLease()
    assert lease.acquire("lease:channel:10", "owner-a", 60)
    assert not lease.acquire("lease:channel:10", "owner-b", 60)
    assert lease.renew("lease:channel:10", "owner-a", 60)
    assert not lease.renew("lease:channel:10", "owner-b", 60)
    lease.release("lease:channel:10", "owner-b")
    assert lease.owner("lease:channel:10") == "owner-a"
    lease.release("lease:channel:10", "owner-a")
    # a zero ttl lease is already expired for the next owner
    assert lease.acquire("lease:channel:10", "owner-b", 0)
    assert lease.acquire("lease:channel:10", "owner-c", 60)


def test_gateway_outbound_then_reply_roundtrip():
    state = RelayState()
    state.ingest(message_envelope())
    state.ingest(
        message_envelope(
            event_type="message.final",
            source_type="agent",
            event_id="evt-2",
            role="assistant",
            content="done",
            stream_id="stream-1",
        )
    )
    snapshot = channel_snapshot()
    gateway = WecomGateway(
        state,
        snapshot,
        Settings(),
        lease=wecom.MemoryLease(),
        requests=wecom.MemoryRequestMap(),
    )
    channel = snapshot.channels[10]
    conn = WecomConnection(FakeWebSocket(), channel)
    gateway.connections[10] = conn

    asyncio.run(gateway.drain_outbox())
    assert len(conn.websocket.sent) == 1
    callback = conn.websocket.sent[0]
    assert callback["cmd"] == wecom.CMD_CALLBACK
    req_id = callback["headers"]["req_id"]
    assert state.list_outbox()[0].state == "sent"
    assert gateway.requests.get(req_id)["turn_id"] == "turn:1"

    reply = {
        "cmd": wecom.CMD_RESPOND,
        "headers": {"req_id": req_id},
        "body": {
            "msgtype": "stream",
            "stream": {"id": "st-2", "finish": True, "content": "hi", "seq": 1},
        },
    }
    result = asyncio.run(gateway._handle_frame(conn, reply))
    assert result is None
    assert conn.websocket.sent[-1]["errcode"] == 0
    record = state.events[-1]
    assert record["event_type"] == "message.final"
    assert record["meta"]["origin"] == "channel"
    assert record["route"]["channel_id"] == 10
    # no echo: the channel reply does not create another outbox entry
    assert len(state.list_outbox()) == 1


def test_unknown_req_id_is_acked_but_not_routed():
    state = RelayState()
    gateway = WecomGateway(
        state,
        channel_snapshot(),
        Settings(),
        lease=wecom.MemoryLease(),
        requests=wecom.MemoryRequestMap(),
    )
    conn = WecomConnection(FakeWebSocket(), wecom_channel())
    frame = {
        "cmd": wecom.CMD_RESPOND,
        "headers": {"req_id": "unknown"},
        "body": {"msgtype": "text", "text": {"content": "hi"}},
    }
    asyncio.run(gateway._handle_frame(conn, frame))
    assert conn.websocket.sent[-1]["errcode"] == 0
    assert state.events == []


def wecom_channel() -> ChannelConfig:
    return channel_snapshot().channels[10]


def test_ws_subscribe_authenticates_and_pings():
    app = create_app(settings=Settings(), snapshot=channel_snapshot())
    with TestClient(app) as client:
        with client.websocket_connect("/v1/channel/wecom/ws") as ws:
            ws.send_json(
                {"cmd": "aibot_subscribe", "headers": {"req_id": "sub-1"},
                 "body": {"bot_id": "bot-1", "secret": "s3cret"}}
            )
            assert ws.receive_json()["errcode"] == 0
            ws.send_json({"cmd": "ping", "headers": {"req_id": "ping-1"}})
            pong = ws.receive_json()
            assert pong["headers"]["req_id"] == "ping-1"
            assert pong["errcode"] == 0


def test_ws_subscribe_rejects_bad_secret():
    app = create_app(settings=Settings(), snapshot=channel_snapshot())
    with TestClient(app) as client:
        with client.websocket_connect("/v1/channel/wecom/ws") as ws:
            ws.send_json(
                {"cmd": "aibot_subscribe", "headers": {"req_id": "sub-1"},
                 "body": {"bot_id": "bot-1", "secret": "wrong"}}
            )
            response = ws.receive_json()
            assert response["errcode"] == wecom.AUTH_FAILED_ERRCODE
