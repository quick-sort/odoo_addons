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


@tagged("post_install", "-at_install")
class TestRecordBehaviors(common.TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Channel = cls.env["agenthub.channel"]
        cls.Agent = cls.env["agenthub.agent"]
        cls.Thread = cls.env["agenthub.thread"]

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
        return self.Agent.create({"name": name, "agent_type": FAKE_AGENT})

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
