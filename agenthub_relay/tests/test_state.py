from agenthub_relay.state import RelayState

from .helpers import (
    command_envelope,
    message_envelope,
    presence_envelope,
    turn_envelope,
)


def test_user_message_creates_turn_and_delivery():
    state = RelayState()
    assert state.ingest(message_envelope()) == "accepted"
    turn = state.turns["turn:1"]
    assert turn.state == "queued"
    assert len(state.deliveries) == 1
    delivery = next(iter(state.deliveries.values()))
    assert delivery.agent_id == 1
    assert delivery.state == "queued"
    assert delivery.kind == "message"


def test_claim_and_ack():
    state = RelayState()
    state.ingest(message_envelope())
    claimed = state.claim(1)
    assert len(claimed) == 1
    delivery = claimed[0]
    assert delivery.state == "claimed"
    assert delivery.attempt == 1
    assert delivery.lease_until is not None
    state.ack(delivery.delivery_id, "done")
    assert delivery.state == "done"
    assert state.get_presence(1)["state"] == "online"


def test_agent_final_creates_outbox():
    state = RelayState()
    state.ingest(message_envelope())
    state.ingest(
        message_envelope(
            event_type="message.final",
            source_type="agent",
            event_id="evt-2",
            role="assistant",
            content="done",
            message_id="msg-2",
            stream_id="stream-1",
            final=True,
        )
    )
    assert len(state.outbox) == 1
    outbox = next(iter(state.outbox.values()))
    assert outbox.channel_id == 10
    assert outbox.message["content"] == "done"


def test_thread_serializes_turns():
    state = RelayState()
    state.ingest(message_envelope(event_id="evt-1", turn_id="turn:1"))
    state.ingest(message_envelope(event_id="evt-2", turn_id="turn:2"))
    assert state.active_turns["thread:1"] == "turn:1"
    assert list(state.backlog["thread:1"]) == ["turn:2"]
    assert not any(
        delivery.turn_id == "turn:2" for delivery in state.deliveries.values()
    )

    state.ingest(
        turn_envelope(
            event_id="evt-3", turn_id="turn:1", state="completed"
        )
    )
    assert state.active_turns["thread:1"] == "turn:2"
    assert any(
        delivery.turn_id == "turn:2" for delivery in state.deliveries.values()
    )


def test_duplicate_event_and_message():
    state = RelayState()
    envelope = message_envelope()
    assert state.ingest(envelope) == "accepted"
    assert state.ingest(envelope) == "duplicate"

    duplicate_message = message_envelope(
        event_id="evt-2", message_id="msg-1", turn_id="turn:1"
    )
    assert state.ingest(duplicate_message) == "duplicate"


def test_lease_expiry_requeues():
    state = RelayState(lease_seconds=0)
    state.ingest(message_envelope())
    delivery = state.claim(1, now=100.0)[0]
    assert delivery.state == "claimed"
    state.expire_leases(now=101.0)
    assert delivery.state == "queued"


def test_max_attempts_marks_dead():
    state = RelayState(max_attempts=2)
    state.ingest(message_envelope())
    delivery = state.claim(1)[0]
    state.ack(delivery.delivery_id, "failed", "boom")
    assert delivery.state == "queued"
    delivery = state.claim(1)[0]
    state.ack(delivery.delivery_id, "failed", "boom")
    assert delivery.state == "dead"


def test_command_delivery():
    state = RelayState()
    assert state.ingest(command_envelope()) == "accepted"
    delivery = next(iter(state.deliveries.values()))
    assert delivery.kind == "command"
    assert delivery.payload["command_id"] == "cmd-1"


def test_outbox_claim_and_ack():
    state = RelayState()
    state.ingest(message_envelope())
    state.ingest(
        message_envelope(
            event_type="message.final",
            source_type="agent",
            event_id="evt-2",
            role="assistant",
            stream_id="s1",
            final=True,
        )
    )
    outbox = state.claim_outbox(10)[0]
    assert outbox.state == "sending"
    state.ack_outbox(outbox.outbox_id, sent=True)
    assert outbox.state == "sent"


def test_record_feed_cursor():
    state = RelayState()
    state.ingest(message_envelope())
    events, next_cursor = state.record_events(0, 10)
    assert len(events) == 1
    assert next_cursor == 1
    assert state.record_events(next_cursor, 10) == ([], next_cursor)
    assert state.ack_record(next_cursor) == 1


def test_presence_not_recorded():
    state = RelayState()
    state.ingest(presence_envelope())
    assert state.get_presence(1)["state"] == "online"
    assert state.events == []
