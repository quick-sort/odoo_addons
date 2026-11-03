import json
import time

from starlette.testclient import TestClient

from agenthub_relay.app import create_app, sign_body
from agenthub_relay.config import AgentConfig, ConfigSnapshot, Settings
from agenthub_relay.protocol import hash_token
from agenthub_relay.state import RelayState

from .helpers import message_envelope


def _client(secret="secret"):
    snapshot = ConfigSnapshot(
        version=1,
        agents={1: AgentConfig(1, hash_token("agent-token"))},
        identities={(10, "peer"): 5},
        bindings={(5, 10): 1},
    )
    settings = Settings(publish_secret=secret)
    relay = RelayState(lease_seconds=60, max_attempts=5)
    app = create_app(settings=settings, snapshot=snapshot, relay=relay)
    return TestClient(app), relay


def _signed_headers(secret, body):
    timestamp = str(int(time.time()))
    signature = sign_body(secret, body, timestamp)
    return {
        "X-AgentHub-Timestamp": timestamp,
        "X-AgentHub-Signature": signature,
        "Content-Type": "application/json",
    }


def test_health_and_metrics():
    client, _ = _client()
    assert client.get("/healthz").status_code == 200
    assert "agenthub_agents_online" in client.get("/metrics").text


def test_publish_and_duplicate():
    client, relay = _client()
    envelope = message_envelope(event_id="evt-1")
    body = json.dumps(envelope).encode()
    response = client.post(
        "/v1/publish", content=body, headers=_signed_headers("secret", body)
    )
    assert response.status_code == 200
    assert response.json()["status"] == "accepted"
    assert len(relay.turns) == 1

    duplicate = client.post(
        "/v1/publish", content=body, headers=_signed_headers("secret", body)
    )
    assert duplicate.status_code == 200
    assert duplicate.json()["status"] == "duplicate"


def test_publish_rejects_bad_signature():
    client, _ = _client()
    envelope = message_envelope(event_id="evt-1")
    body = json.dumps(envelope).encode()
    headers = _signed_headers("wrong", body)
    response = client.post("/v1/publish", content=body, headers=headers)
    assert response.status_code == 401


def test_record_feed_and_ack():
    client, relay = _client()
    envelope = message_envelope(event_id="evt-1")
    body = json.dumps(envelope).encode()
    client.post(
        "/v1/publish", content=body, headers=_signed_headers("secret", body)
    )
    headers = {"X-AgentHub-Recorder-Token": "dev-recorder"}
    response = client.get("/v1/record?cursor=0&limit=10", headers=headers)
    data = response.json()
    assert len(data["events"]) == 1
    assert data["next_cursor"] == 1
    ack = client.post(
        "/v1/record/ack",
        json={"cursor": data["next_cursor"]},
        headers=headers,
    )
    assert ack.status_code == 200
    assert relay.record_cursor_acked == 1


def test_record_feed_requires_token():
    client, _ = _client()
    assert client.get("/v1/record").status_code == 401
    assert client.post("/v1/record/ack", json={"cursor": 0}).status_code == 401


def test_agent_websocket_auth():
    client, _ = _client()
    with client.websocket_connect("/v1/agent/ws") as websocket:
        websocket.send_json(
            {"type": "auth", "agent_id": 1, "token": "agent-token"}
        )
        hello = websocket.receive_json()
        assert hello["type"] == "hello"
