import asyncio
from types import SimpleNamespace

from agenthub_relay.config import ConfigSnapshot, Settings
from agenthub_relay.config_sync import sync_once
from agenthub_relay.protocol import AgentDirectory
from agenthub_relay.router import Router


def test_snapshot_from_dict():
    snapshot = ConfigSnapshot.from_dict(
        {
            "version": 7,
            "agents": [{"id": 1, "token_hash": "hash", "active": True}],
            "identities": [
                {"channel_id": 10, "peer_ref": "peer", "user_id": 5}
            ],
            "bindings": [
                {"user_id": 5, "channel_id": 10, "agent_id": 1}
            ],
        }
    )
    assert snapshot.version == 7
    assert snapshot.agents[1].token_hash == "hash"
    assert snapshot.identities[(10, "peer")] == 5
    assert snapshot.bindings[(5, 10)] == 1


def test_sync_once_applies_snapshot():
    class FakeResponse:
        status_code = 200

        def json(self):
            return {
                "version": 2,
                "agents": [{"id": 1, "token_hash": "hash", "active": True}],
                "identities": [],
                "bindings": [],
            }

    class FakeClient:
        async def get(self, *args, **kwargs):
            return FakeResponse()

    snapshot = ConfigSnapshot()
    app = SimpleNamespace(
        state=SimpleNamespace(
            settings=Settings(
                odoo_config_url="http://odoo.test",
                odoo_config_token="token",
            ),
            snapshot=snapshot,
            directory=AgentDirectory({}),
            router=Router(snapshot),
        )
    )
    changed = asyncio.run(sync_once(app, FakeClient()))
    assert changed
    assert snapshot.version == 2
    assert snapshot.agents[1].token_hash == "hash"
    assert app.state.directory.verify(1, "") is False
