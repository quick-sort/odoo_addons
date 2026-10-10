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

    def test_agent_has_owner_and_channels(self):
        agent_fields = self.env["agenthub.agent"]._fields
        self.assertIn("user_id", agent_fields)
        self.assertIn("channel_ids", agent_fields)

    def test_channel_belongs_to_one_agent(self):
        field = self.env["agenthub.channel"]._fields["agent_id"]
        self.assertTrue(field.required)
        self.assertEqual(field.comodel_name, "agenthub.agent")

    def test_thread_has_no_agent_field(self):
        self.assertNotIn("agent_id", self.env["agenthub.thread"]._fields)

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
        self.agent = self._make_agent()

    def _add_selection(self, model, field, value):
        ctx = selection_value(model, field, value)
        ctx.__enter__()
        self.addCleanup(ctx.__exit__, None, None, None)

    def _make_channel(self, name="Test Channel", agent=None):
        return self.Channel.create(
            {
                "name": name,
                "channel_type": FAKE_CHANNEL,
                "agent_id": (agent or self.agent).id,
            }
        )

    def _make_agent(self, name="Test Agent", user=None):
        return self.Agent.create(
            {
                "name": name,
                "agent_type": FAKE_AGENT,
                "user_id": user.id if user else False,
            }
        )

    def test_thread_unique_constraint(self):
        from psycopg2 import IntegrityError

        channel = self._make_channel()
        self.Thread.create(
            {"name": "peer", "channel_id": channel.id, "peer_ref": "peer"}
        )
        with self.assertRaises(IntegrityError), self.cr.savepoint():
            self.Thread.create(
                {
                    "name": "peer again",
                    "channel_id": channel.id,
                    "peer_ref": "peer",
                }
            )

    def test_find_or_create_reuses_existing(self):
        channel = self._make_channel()
        thread = self.Thread._find_or_create(channel.id, "peer")
        again = self.Thread._find_or_create(channel.id, "peer")
        self.assertEqual(thread, again)

    def test_find_or_create_creates_when_missing(self):
        channel = self._make_channel()
        thread = self.Thread._find_or_create(channel.id, "peer")
        self.assertTrue(thread.id)
        self.assertEqual(thread.peer_ref, "peer")
        self.assertEqual(thread.channel_id, channel)

    def test_thread_agent_derives_from_channel(self):
        agent = self._make_agent(name="Other Agent")
        channel = self._make_channel(agent=agent)
        thread = self.Thread._find_or_create(channel.id, "peer")
        self.assertEqual(thread.channel_id.agent_id, agent)

    def test_agent_without_user_is_system(self):
        agent = self._make_agent(user=None)
        self.assertFalse(agent.user_id)

    def test_agent_owns_channels(self):
        agent = self._make_agent(name="Owner Agent")
        channel_1 = self._make_channel(name="c1", agent=agent)
        channel_2 = self._make_channel(name="c2", agent=agent)
        self.assertEqual(agent.channel_ids, channel_1 | channel_2)
        self.assertEqual(channel_1.agent_id, agent)
        self.assertEqual(channel_2.agent_id, agent)

    def test_agent_delete_cascades_channels(self):
        agent = self._make_agent(name="Doomed Agent")
        channel = self._make_channel(agent=agent)
        agent.unlink()
        self.assertFalse(channel.exists())
