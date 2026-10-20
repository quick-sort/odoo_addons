from odoo.exceptions import ValidationError
from odoo.tests import common, tagged

from .common import selection_value

FAKE_CHANNEL = "test_channel"
FAKE_AGENT = "test_agent"


@tagged("post_install", "-at_install")
class TestModelDefinitions(common.TransactionCase):
    """Field/inheritance definitions, checked without creating records."""

    def test_models_exist(self):
        self.assertTrue(self.env["agenthub.channel"]._name)
        self.assertTrue(self.env["agenthub.agent"]._name)
        self.assertTrue(self.env["agenthub.thread"]._name)

    def test_channel_and_agent_are_collections(self):
        # collection.base contributes work_on(); asserting the method exists is
        # the behavioural check — the _inherit list's runtime shape is an Odoo
        # implementation detail that shifts once an extension addon _inherit's
        # the model.
        self.assertTrue(hasattr(self.env["agenthub.channel"], "work_on"))
        self.assertTrue(hasattr(self.env["agenthub.agent"], "work_on"))

    def test_thread_is_a_mail_thread(self):
        self.assertIn("mail.thread", self.env["agenthub.thread"]._inherit)

    def test_mail_message_has_agenthub_fields(self):
        message_fields = self.env["mail.message"]._fields
        for name in (
            "agenthub_role",
            "agenthub_direction",
            "agenthub_external_id",
            "agenthub_reply_to_external_id",
            "agenthub_delivery_state",
            "agenthub_stream_id",
            "agenthub_content",
        ):
            self.assertIn(name, message_fields)

    def test_agent_has_identity_fields(self):
        agent_fields = self.env["agenthub.agent"]._fields
        for name in ("user_id", "owner_user_id", "partner_id"):
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
        self._add_selection(self.Channel, "channel_type", FAKE_CHANNEL)
        self._add_selection(self.Agent, "agent_type", FAKE_AGENT)

    def _add_selection(self, model, field, value):
        ctx = selection_value(model, field, value)
        ctx.__enter__()
        self.addCleanup(ctx.__exit__, None, None, None)

    def _make_channel(self, name="Test Channel"):
        return self.Channel.create({"name": name, "channel_type": FAKE_CHANNEL})

    def _make_agent(self, name="Test Agent"):
        return self.Agent.create(
            {
                "name": name,
                "agent_type": FAKE_AGENT,
                "user_id": self.user_admin.id,
            }
        )

    def test_thread_unique_constraint(self):
        from psycopg2 import IntegrityError

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
                "groups_id": [(6, 0, [cls.env.ref("base.group_user").id])],
            }
        )

    def setUp(self):
        super().setUp()
        self._add_selection(self.Agent, "agent_type", FAKE_AGENT)

    def _add_selection(self, model, field, value):
        ctx = selection_value(model, field, value)
        ctx.__enter__()
        self.addCleanup(ctx.__exit__, None, None, None)

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
                "groups_id": [(6, 0, [self.env.ref("base.group_portal").id])],
            }
        )
        with self.assertRaises(ValidationError):
            self._make_agent(user_id=portal.id)

    def test_constraint_rejects_owner_as_execution_user(self):
        with self.assertRaises(ValidationError):
            self._make_agent(
                user_id=self.user_admin.id,
                owner_user_id=self.user_admin.id,
            )

    def test_constraint_accepts_internal_user(self):
        agent = self._make_agent()
        self.assertTrue(agent.id)
