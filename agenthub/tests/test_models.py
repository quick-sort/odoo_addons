import uuid

from psycopg2 import IntegrityError

from odoo.exceptions import ValidationError
from odoo.tests import common, tagged

from .common import selection_value

FAKE_CHANNEL = "test_channel"
FAKE_AGENT = "test_agent"


def _add_selection(test, model, field, value):
    ctx = selection_value(model, field, value)
    ctx.__enter__()
    test.addCleanup(ctx.__exit__, None, None, None)


@tagged("post_install", "-at_install")
class TestModelDefinitions(common.TransactionCase):
    """Field/inheritance definitions, checked without creating records."""

    def test_models_exist(self):
        for name in (
            "agenthub.channel",
            "agenthub.agent",
            "agenthub.thread",
            "agenthub.turn",
            "agenthub.command",
            "agenthub.identity",
            "agenthub.binding",
            "agenthub.delivery",
            "agenthub.publish",
            "agenthub.record.cursor",
        ):
            self.assertTrue(self.env[name]._name, name)

    def test_channel_and_agent_are_collections(self):
        self.assertTrue(hasattr(self.env["agenthub.channel"], "work_on"))
        self.assertTrue(hasattr(self.env["agenthub.agent"], "work_on"))

    def test_thread_is_a_mail_thread(self):
        self.assertIn("mail.thread", self.env["agenthub.thread"]._inherit)

    def test_mail_message_has_agenthub_fields(self):
        message_fields = self.env["mail.message"]._fields
        for name in (
            "agenthub_role",
            "agenthub_direction",
            "agenthub_content",
            "agenthub_body_json",
            "agenthub_is_error",
            "agenthub_external_id",
            "agenthub_reply_to_external_id",
            "agenthub_delivery_state",
            "agenthub_relay_message_id",
            "agenthub_relay_turn_id",
            "agenthub_turn_id",
            "agenthub_stream_id",
        ):
            self.assertIn(name, message_fields)

    def test_agenthub_message_subtypes(self):
        id_to_role, role_to_id = self.env["mail.message"].get_agenthub_roles()
        for role in ("user", "assistant", "tool", "system"):
            self.assertIn(role, role_to_id)
            self.assertIn(role_to_id[role], id_to_role)

    def test_agent_has_identity_fields(self):
        agent_fields = self.env["agenthub.agent"]._fields
        for name in (
            "user_id",
            "owner_user_id",
            "partner_id",
            "runtime",
            "token_hash",
            "state",
            "last_seen",
            "workspace",
            "api_key",
        ):
            self.assertIn(name, agent_fields)


@tagged("post_install", "-at_install")
class TestRecordBehaviors(common.TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Channel = cls.env["agenthub.channel"]
        cls.Agent = cls.env["agenthub.agent"]
        cls.Thread = cls.env["agenthub.thread"]
        cls.user_admin = cls.env.ref("base.user_admin")

    def setUp(self):
        super().setUp()
        _add_selection(self, self.Channel, "channel_type", FAKE_CHANNEL)
        _add_selection(self, self.Agent, "agent_type", FAKE_AGENT)

    def _make_user(self, label="Agent User"):
        return self.env["res.users"].create(
            {
                "name": label,
                "login": f"{label.lower().replace(' ', '_')}_{uuid.uuid4().hex[:8]}",
                "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
            }
        )

    def _make_channel(self, name="Test Channel"):
        return self.Channel.create({"name": name, "channel_type": FAKE_CHANNEL})

    def _make_agent(self, name="Test Agent", user=None):
        user = user or self._make_user(name)
        return self.Agent.create(
            {
                "name": name,
                "agent_type": FAKE_AGENT,
                "user_id": user.id,
                "runtime": "in_process",
            }
        )

    def test_thread_unique_constraint(self):
        channel = self._make_channel()
        agent = self._make_agent()
        self.Thread.create(
            {
                "name": "peer",
                "channel_id": channel.id,
                "peer_ref": "peer",
                "agent_id": agent.id,
            }
        )
        with self.assertRaises(IntegrityError), self.cr.savepoint():
            self.Thread.create(
                {
                    "name": "peer again",
                    "channel_id": channel.id,
                    "peer_ref": "peer",
                    "agent_id": agent.id,
                }
            )

    def test_thread_same_peer_other_agent_allowed(self):
        channel = self._make_channel()
        agent_a = self._make_agent("Agent A")
        agent_b = self._make_agent("Agent B")
        self.Thread.create(
            {
                "name": "peer",
                "channel_id": channel.id,
                "peer_ref": "peer",
                "agent_id": agent_a.id,
            }
        )
        thread_b = self.Thread.create(
            {
                "name": "peer",
                "channel_id": channel.id,
                "peer_ref": "peer",
                "agent_id": agent_b.id,
            }
        )
        self.assertTrue(thread_b.id)

    def test_find_or_create_reuses_existing(self):
        channel = self._make_channel()
        agent = self._make_agent()
        thread = self.Thread._find_or_create(channel.id, "peer", agent.id)
        again = self.Thread._find_or_create(channel.id, "peer", agent.id)
        self.assertEqual(thread, again)

    def test_find_or_create_creates_when_missing(self):
        channel = self._make_channel()
        agent = self._make_agent()
        thread = self.Thread._find_or_create(channel.id, "peer", agent.id)
        self.assertTrue(thread.id)
        self.assertEqual(thread.peer_ref, "peer")
        self.assertEqual(thread.agent_id, agent)
        self.assertEqual(
            thread.relay_thread_key,
            f"agenthub:channel:{channel.id}:peer:peer:agent:{agent.id}",
        )

    def test_find_or_create_discuss_key(self):
        channel = self._make_channel()
        agent = self._make_agent()
        discuss = self.env["discuss.channel"].create({"name": "DM"})
        thread = self.Thread._find_or_create(
            channel.id,
            "peer",
            agent.id,
            relay_thread_key=f"discuss.channel:{discuss.id}",
            discuss_channel_id=discuss.id,
        )
        self.assertEqual(thread.discuss_channel_id, discuss)
        self.assertEqual(thread.relay_thread_key, f"discuss.channel:{discuss.id}")


@tagged("post_install", "-at_install")
class TestAgentIdentity(common.TransactionCase):
    """Execution-identity fields and the constraints guarding them."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Agent = cls.env["agenthub.agent"]
        cls.user_admin = cls.env.ref("base.user_admin")
        cls.service_user = cls.env["res.users"].create(
            {
                "name": "Agent Service",
                "login": "agent_service_agenthub_test",
                "group_ids": [(6, 0, [cls.env.ref("base.group_user").id])],
            }
        )

    def setUp(self):
        super().setUp()
        _add_selection(self, self.Agent, "agent_type", FAKE_AGENT)

    def _make_agent(self, **vals):
        base = {
            "name": "Agent",
            "agent_type": FAKE_AGENT,
            "user_id": self.service_user.id,
        }
        base.update(vals)
        return self.Agent.create(base)

    def test_agent_env_binds_execution_user(self):
        agent = self._make_agent()
        env = agent._agent_env()
        self.assertEqual(env.uid, self.service_user.id)
        self.assertFalse(env.su)

    def test_agent_env_not_sudo_even_from_sudo(self):
        agent = self._make_agent()
        env = agent.sudo()._agent_env()
        self.assertFalse(env.su)

    def test_partner_id_follows_user(self):
        agent = self._make_agent()
        self.assertEqual(agent.partner_id, self.service_user.partner_id)

    def test_constraint_rejects_portal_user(self):
        portal = self.env["res.users"].create(
            {
                "name": "Portal",
                "login": "portal_agenthub_test",
                "group_ids": [(6, 0, [self.env.ref("base.group_portal").id])],
            }
        )
        with self.assertRaises(ValidationError):
            self._make_agent(user_id=portal.id)

    def test_allows_owner_as_execution_user(self):
        agent = self._make_agent(
            user_id=self.user_admin.id,
            owner_user_id=self.user_admin.id,
        )
        self.assertEqual(agent.user_id, agent.owner_user_id)

    def test_constraint_accepts_internal_user(self):
        agent = self._make_agent()
        self.assertTrue(agent.id)

    def test_unique_service_user(self):
        other_user = self.env["res.users"].create(
            {
                "name": "Other Service",
                "login": "other_service_agenthub_test",
                "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
            }
        )
        self._make_agent(user_id=other_user.id)
        with self.assertRaises(ValidationError):
            self._make_agent(name="Second", user_id=other_user.id)

    def test_token_roundtrip(self):
        agent = self._make_agent()
        token = agent._generate_token()
        self.assertTrue(agent.token_hash)
        self.assertTrue(agent._check_token(token))
        self.assertFalse(agent._check_token("wrong-token"))

    def test_default_owner_and_execution_user(self):
        user = self.env["res.users"].create(
            {
                "name": "Default Owner",
                "login": "agenthub_default_owner",
                "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
            }
        )
        agent = self.Agent.with_user(user).create(
            {"name": "Default Identity", "agent_type": FAKE_AGENT}
        )
        self.assertEqual(agent.user_id, user)
        self.assertEqual(agent.owner_user_id, user)

    def test_user_sees_only_own_agents(self):
        group_user = self.env.ref("base.group_user")
        user_a = self.env["res.users"].create(
            {
                "name": "Owner A",
                "login": "agenthub_owner_a",
                "group_ids": [(6, 0, [group_user.id])],
            }
        )
        user_b = self.env["res.users"].create(
            {
                "name": "Owner B",
                "login": "agenthub_owner_b",
                "group_ids": [(6, 0, [group_user.id])],
            }
        )
        agent_a = self.Agent.create(
            {
                "name": "Agent A",
                "agent_type": FAKE_AGENT,
                "owner_user_id": user_a.id,
                "user_id": user_a.id,
            }
        )
        agent_b = self.Agent.create(
            {
                "name": "Agent B",
                "agent_type": FAKE_AGENT,
                "owner_user_id": user_b.id,
                "user_id": user_b.id,
            }
        )
        visible = self.env["agenthub.agent"].with_user(user_a).search([])
        self.assertIn(agent_a, visible)
        self.assertNotIn(agent_b, visible)


@tagged("post_install", "-at_install")
class TestRelayModels(common.TransactionCase):
    """Identity/binding/turn/command/delivery/cursor behaviors."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Channel = cls.env["agenthub.channel"]
        cls.Agent = cls.env["agenthub.agent"]
        cls.Thread = cls.env["agenthub.thread"]
        cls.Turn = cls.env["agenthub.turn"]

    def setUp(self):
        super().setUp()
        _add_selection(self, self.Channel, "channel_type", FAKE_CHANNEL)
        _add_selection(self, self.Agent, "agent_type", FAKE_AGENT)
        self.channel = self.Channel.create(
            {"name": "Relay Channel", "channel_type": FAKE_CHANNEL}
        )
        self.user = self.env["res.users"].create(
            {
                "name": "Relay User",
                "login": f"relay_user_{uuid.uuid4().hex[:8]}",
                "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
            }
        )
        self.agent = self.Agent.create(
            {
                "name": "Relay Agent",
                "agent_type": FAKE_AGENT,
                "user_id": self.user.id,
                "runtime": "relay",
            }
        )
        self.thread = self.Thread._find_or_create(
            self.channel.id, "peer", self.agent.id
        )

    def _turn(self, relay_turn_id="turn-1", **vals):
        data = {
            "thread_id": self.thread.id,
            "agent_id": self.agent.id,
            "relay_turn_id": relay_turn_id,
        }
        data.update(vals)
        return self.Turn.create(data)

    def test_identity_unique(self):
        Identity = self.env["agenthub.identity"]
        Identity.create(
            {
                "channel_id": self.channel.id,
                "peer_ref": "peer",
                "user_id": self.user.id,
            }
        )
        with self.assertRaises(IntegrityError), self.cr.savepoint():
            Identity.create(
                {
                    "channel_id": self.channel.id,
                    "peer_ref": "peer",
                    "user_id": self.user.id,
                }
            )

    def test_binding_unique(self):
        Binding = self.env["agenthub.binding"]
        Binding.create(
            {
                "user_id": self.user.id,
                "channel_id": self.channel.id,
                "agent_id": self.agent.id,
            }
        )
        with self.assertRaises(IntegrityError), self.cr.savepoint():
            Binding.create(
                {
                    "user_id": self.user.id,
                    "channel_id": self.channel.id,
                    "agent_id": self.agent.id,
                }
            )

    def test_turn_single_active(self):
        first = self._turn("turn-1")
        with self.assertRaises(ValidationError):
            self._turn("turn-2")
        first.write({"state": "completed"})
        self.assertFalse(first.is_active)
        second = self._turn("turn-2")
        self.assertTrue(second.is_active)

    def test_turn_terminal_state_clears_active(self):
        turn = self._turn()
        turn.write({"state": "failed"})
        self.assertFalse(turn.is_active)

    def test_command_defaults(self):
        command = self.env["agenthub.command"].create(
            {"name": "run_tests", "agent_id": self.agent.id}
        )
        self.assertEqual(command.reply_mode, "none")
        self.assertEqual(command.state, "draft")
        command.write({"state": "queued", "reply_mode": "owner"})
        self.assertEqual(command.reply_mode, "owner")

    def test_delivery_audit(self):
        turn = self._turn()
        delivery = self.env["agenthub.delivery"].create(
            {
                "turn_id": turn.id,
                "agent_id": self.agent.id,
                "channel_id": self.channel.id,
                "leg": "to_agent",
            }
        )
        self.assertEqual(delivery.state, "queued")
        delivery.write({"state": "done"})
        self.assertEqual(delivery.state, "done")

    def test_record_cursor_get_set(self):
        Cursor = self.env["agenthub.record.cursor"]
        record = Cursor._get("default")
        self.assertEqual(record.key, "default")
        Cursor._set("cursor-1", key="default", lag_seconds=1.5)
        self.assertEqual(record.cursor, "cursor-1")
        self.assertEqual(record.lag_seconds, 1.5)
        self.assertEqual(Cursor._get("default"), record)
