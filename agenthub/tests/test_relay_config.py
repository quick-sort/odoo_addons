import uuid

from odoo.tests import HttpCase, common, tagged

from .common import selection_value

FAKE_CHANNEL = "test_config_channel"
FAKE_AGENT = "test_config_agent"


def _add_selection(test, model, field, value):
    ctx = selection_value(model, field, value)
    ctx.__enter__()
    test.addCleanup(ctx.__exit__, None, None, None)


@tagged("post_install", "-at_install")
class TestRelayConfigSnapshot(common.TransactionCase):
    def setUp(self):
        super().setUp()
        _add_selection(self, self.env["agenthub.channel"], "channel_type", FAKE_CHANNEL)
        _add_selection(self, self.env["agenthub.agent"], "agent_type", FAKE_AGENT)
        self.user = self.env["res.users"].create(
            {
                "name": "Config User",
                "login": f"config_{uuid.uuid4().hex[:8]}",
                "group_ids": [(6, 0, [self.env.ref("agenthub.group_agenthub_user").id])],
            }
        )
        self.channel = self.env["agenthub.channel"].create(
            {"name": "Config Channel", "channel_type": FAKE_CHANNEL}
        )
        self.agent = self.env["agenthub.agent"].create(
            {
                "name": "Config Agent",
                "agent_type": FAKE_AGENT,
                "user_id": self.user.id,
                "runtime": "relay",
                "token_hash": "hash",
            }
        )
        self.env["agenthub.identity"].create(
            {
                "channel_id": self.channel.id,
                "peer_ref": "peer",
                "user_id": self.user.id,
            }
        )
        self.env["agenthub.binding"].create(
            {
                "user_id": self.user.id,
                "channel_id": self.channel.id,
                "agent_id": self.agent.id,
            }
        )

    def test_snapshot_contains_routing_config(self):
        snapshot = self.env["agenthub.relay.config"]._snapshot()
        self.assertGreater(snapshot["version"], 0)
        self.assertEqual(snapshot["agents"][0]["token_hash"], "hash")
        self.assertEqual(
            snapshot["identities"][0],
            {
                "channel_id": self.channel.id,
                "peer_ref": "peer",
                "user_id": self.user.id,
            },
        )
        self.assertEqual(
            snapshot["bindings"][0],
            {
                "user_id": self.user.id,
                "channel_id": self.channel.id,
                "agent_id": self.agent.id,
            },
        )


@tagged("post_install", "-at_install")
class TestRelayConfigEndpoint(HttpCase):
    def test_token_required(self):
        self.env["ir.config_parameter"].sudo().set_param(
            "agenthub.relay_config_token", "secret"
        )
        response = self.url_open("/agenthub/relay/config")
        self.assertEqual(response.status_code, 401)
        response = self.url_open(
            "/agenthub/relay/config",
            headers={"X-AgentHub-Config-Token": "secret"},
        )
        self.assertEqual(response.status_code, 200)
        self.assertIn("agents", response.json())
