import os
import uuid

import pytest

from agenthub_relay.redis_state import RedisRelayState
from agenthub_relay.wecom import RedisLease, RedisRequestMap

from .helpers import (
    command_envelope,
    message_envelope,
    presence_envelope,
    turn_envelope,
)

redis = pytest.importorskip("redis")

REDIS_URL = os.environ.get(
    "AGENTHUB_TEST_REDIS_URL", "redis://127.0.0.1:6379/15"
)


@pytest.fixture
def redis_client():
    try:
        client = redis.Redis.from_url(
            REDIS_URL, decode_responses=True, socket_connect_timeout=1
        )
        client.ping()
    except Exception as exc:  # noqa: BLE001 - environment probe
        pytest.skip(f"redis unavailable: {exc}")
    yield client
    client.close()


@pytest.fixture
def make_state(redis_client):
    prefix = f"agenthub-test:{uuid.uuid4().hex}:"

    def factory(**kwargs):
        return RedisRelayState(
            prefix=prefix,
            client=redis_client,
            **kwargs,
        )

    yield factory
    for key in redis_client.scan_iter(f"{prefix}*"):
        redis_client.delete(key)


def test_delivery_survives_restart(make_state):
    state = make_state()
    assert state.ingest(message_envelope()) == "accepted"

    restarted = make_state()
    claimed = restarted.claim(1)
    assert len(claimed) == 1
    assert claimed[0].kind == "message"
    assert claimed[0].payload["content"] == "hello"


def test_duplicate_event_rejected_across_restart(make_state):
    state = make_state()
    envelope = message_envelope()
    assert state.ingest(envelope) == "accepted"

    restarted = make_state()
    assert restarted.ingest(envelope) == "duplicate"
    assert len(restarted.list_deliveries()) == 1


def test_record_cursor_does_not_go_backwards(make_state):
    state = make_state()
    state.ingest(message_envelope(event_id="evt-1", message_id="msg-1"))
    events, first_cursor = state.record_events(0, 10)
    assert len(events) == 1
    assert first_cursor > 0

    restarted = make_state()
    restarted.ingest(
        message_envelope(event_id="evt-2", message_id="msg-2", turn_id="turn:2")
    )
    events, second_cursor = restarted.record_events(first_cursor, 10)
    assert [event["event_id"] for event in events] == ["evt-2"]
    assert second_cursor > first_cursor
    assert restarted.record_events(second_cursor, 10) == ([], second_cursor)


def test_ack_record_keeps_safety_margin(make_state):
    state = make_state(record_trim_margin=0)
    state.ingest(message_envelope(event_id="evt-1", message_id="msg-1"))
    _, cursor = state.record_events(0, 10)
    assert state.ack_record(cursor) == cursor
    restarted = make_state(record_trim_margin=0)
    assert restarted.record_events(0, 10) == ([], 0)


def test_app_serves_record_feed_from_redis(make_state):
    from starlette.testclient import TestClient

    from agenthub_relay.app import create_app
    from agenthub_relay.config import Settings

    state = make_state()
    state.ingest(message_envelope())
    app = create_app(settings=Settings(), relay=state)
    with TestClient(app) as client:
        response = client.get(
            "/v1/record",
            headers={"x-agenthub-recorder-token": "dev-recorder"},
        )
        assert response.status_code == 200
        assert len(response.json()["events"]) == 1
        metrics = client.get("/metrics")
        assert "agenthub_record_events_total 1" in metrics.text


def test_ack_after_restart_marks_done(make_state):
    state = make_state()
    state.ingest(message_envelope())
    delivery = state.claim(1)[0]

    restarted = make_state()
    acked = restarted.ack(delivery.delivery_id, "done")
    assert acked is not None
    assert acked.state == "done"
    assert restarted.claim(1) == []
    assert restarted.get_presence(1)["state"] == "online"


def test_lease_expiry_requeues_after_restart(make_state):
    state = make_state(lease_seconds=0)
    state.ingest(message_envelope())
    delivery = state.claim(1, now=100.0)[0]
    assert delivery.state == "claimed"

    restarted = make_state(lease_seconds=0)
    assert restarted.expire_leases(now=101.0) == 1
    reclaimed = restarted.claim(1, now=102.0)
    assert len(reclaimed) == 1
    assert reclaimed[0].attempt == 2


def test_thread_serialization_is_persisted(make_state):
    state = make_state()
    state.ingest(message_envelope(event_id="evt-1", turn_id="turn:1"))
    state.ingest(message_envelope(event_id="evt-2", turn_id="turn:2"))

    restarted = make_state()
    assert restarted.active_turn("thread:1") == "turn:1"
    assert restarted.backlog_ids("thread:1") == ["turn:2"]
    assert not any(
        delivery.turn_id == "turn:2" for delivery in restarted.list_deliveries()
    )

    restarted.ingest(
        turn_envelope(event_id="evt-3", turn_id="turn:1", state="completed")
    )
    assert restarted.active_turn("thread:1") == "turn:2"
    assert any(
        delivery.turn_id == "turn:2" for delivery in restarted.list_deliveries()
    )


def test_outbox_survives_restart(make_state):
    state = make_state()
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

    restarted = make_state()
    claimed = restarted.claim_outbox(10)
    assert len(claimed) == 1
    assert claimed[0].message["content"] == "done"
    restarted.ack_outbox(claimed[0].outbox_id, sent=True)
    assert restarted.list_outbox()[0].state == "sent"


def test_command_delivery_persists(make_state):
    state = make_state()
    assert state.ingest(command_envelope()) == "accepted"

    restarted = make_state()
    delivery = restarted.claim(1)[0]
    assert delivery.kind == "command"
    assert delivery.payload["command_id"] == "cmd-1"


def test_redis_lease_is_single_owner(make_state):
    state = make_state()
    lease = RedisLease(state.redis, prefix=state.prefix)
    assert lease.acquire("lease:channel:1", "owner-a", 60)
    assert not lease.acquire("lease:channel:1", "owner-b", 60)
    assert lease.owner("lease:channel:1") == "owner-a"
    assert lease.renew("lease:channel:1", "owner-a", 60)
    lease.release("lease:channel:1", "owner-b")
    assert lease.owner("lease:channel:1") == "owner-a"
    lease.release("lease:channel:1", "owner-a")
    assert lease.acquire("lease:channel:1", "owner-b", 60)


def test_redis_request_map_and_seq(make_state):
    state = make_state()
    requests = RedisRequestMap(state.redis, prefix=state.prefix)
    requests.put("req-1", {"thread_key": "t"}, 60)
    assert requests.get("req-1") == {"thread_key": "t"}
    assert requests.get("missing") is None
    assert requests.next_seq("stream-1", 60) == 1
    assert requests.next_seq("stream-1", 60) == 2


def test_presence_persists(make_state):
    state = make_state()
    state.ingest(presence_envelope())

    restarted = make_state()
    assert restarted.get_presence(1)["state"] == "online"
    stats = restarted.stats()
    assert stats["agents_online"] == 1
    assert stats["record_events_total"] == 0
