import uuid
from contextlib import contextmanager

from odoo.tests import common, tagged

FAKE_AGENT = "test_discuss_agent"


@contextmanager
def _selection_value(model, field_name, value, label="Test Value"):
    field = type(model)._fields[field_name]
    original_selection = field.selection
    original_lookup = field._selection
    field.selection = list(original_selection) + [(value, label)]
    field._selection = dict(original_lookup or {}, **{value: label})
    try:
        yield
    finally:
        field.selection = original_selection
        field._selection = original_lookup


def _add_agent_type(test):
    ctx = _selection_value(
        test.env["agenthub.agent"], "agent_type", FAKE_AGENT
    )
    ctx.__enter__()
    test.addCleanup(ctx.__exit__, None, None, None)


@tagged("post_install", "-at_install")
class TestDiscussPublish(common.TransactionCase):
    def setUp(self):
        super().setUp()
        _add_agent_type(self)
        self.user = self.env["res.users"].create(
            {
                "name": "Discuss User",
                "login": f"discuss_{uuid.uuid4().hex[:8]}",
                "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
            }
        )
        self.agent_user = self.env["res.users"].create(
            {
                "name": "Discuss Agent Service",
                "login": f"discuss_agent_{uuid.uuid4().hex[:8]}",
                "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
            }
        )
        self.agent = self.env["agenthub.agent"].create(
            {
                "name": "Discuss Agent",
                "agent_type": FAKE_AGENT,
                "user_id": self.agent_user.id,
                "runtime": "relay",
            }
        )
        self.channel = self.env["discuss.channel"].create(
            {"name": "Agent DM"}
        )
        self.thread = self.env["agenthub.thread"].create(
            {
                "name": self.channel.name,
                "peer_ref": f"discuss.channel:{self.channel.id}",
                "agent_id": self.agent.id,
                "relay_thread_key": f"discuss.channel:{self.channel.id}",
                "discuss_channel_id": self.channel.id,
            }
        )

    def _post(self, body="hello", author=None):
        return self.channel.message_post(
            body=body,
            author_id=(author or self.user.partner_id).id,
            message_type="comment",
        )

    def test_user_message_published(self):
        message = self._post()
        publish = self.env["agenthub.publish"].search(
            [("event_id", "=", f"odoo:mail.message:{message.id}:message.created")],
            limit=1,
        )
        self.assertTrue(publish)
        self.assertEqual(publish.event_type, "message.created")
        envelope = publish.envelope
        self.assertEqual(
            envelope["route"]["thread_key"],
            f"discuss.channel:{self.channel.id}",
        )
        self.assertEqual(envelope["route"]["agent_id"], self.agent.id)
        self.assertEqual(envelope["route"]["user_id"], self.user.id)
        self.assertEqual(
            envelope["meta"]["origin_record_id"],
            f"mail.message,{message.id}",
        )
        self.assertEqual(envelope["meta"]["origin"], "odoo")
        self.assertEqual(envelope["payload"]["content"], "hello")

    def test_agent_message_not_published(self):
        self._post()
        before = self.env["agenthub.publish"].search_count([])
        self._post(body="agent reply", author=self.agent.user_id.partner_id)
        self.assertEqual(self.env["agenthub.publish"].search_count([]), before)

    def test_odoo_bot_not_published(self):
        self._post()
        before = self.env["agenthub.publish"].search_count([])
        odoobot = self.env.ref("base.partner_root")
        self._post(body="bot", author=odoobot)
        self.assertEqual(self.env["agenthub.publish"].search_count([]), before)

    def test_unbound_channel_not_published(self):
        other = self.env["discuss.channel"].create({"name": "Other DM"})
        other.message_post(
            body="hello",
            author_id=self.user.partner_id.id,
            message_type="comment",
        )
        self.assertEqual(
            self.env["agenthub.publish"].search_count(
                [("event_type", "=", "message.created")]
            ),
            0,
        )

    def test_publish_is_idempotent(self):
        message = self._post()
        self.channel._agenthub_publish_inbound(message)
        self.assertEqual(
            self.env["agenthub.publish"].search_count(
                [("event_type", "=", "message.created")]
            ),
            1,
        )
