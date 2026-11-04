import uuid

from odoo.exceptions import UserError
from odoo.tests import common, tagged

from .common import selection_value

FAKE_CHANNEL = "test_command_channel"
FAKE_AGENT = "test_command_agent"


def _add_selection(test, model, field, value):
    ctx = selection_value(model, field, value)
    ctx.__enter__()
    test.addCleanup(ctx.__exit__, None, None, None)


@tagged("post_install", "-at_install")
class TestCommandPublish(common.TransactionCase):
    def setUp(self):
        super().setUp()
        _add_selection(self, self.env["agenthub.channel"], "channel_type", FAKE_CHANNEL)
        _add_selection(self, self.env["agenthub.agent"], "agent_type", FAKE_AGENT)
        self.user = self.env["res.users"].create(
            {
                "name": "Command User",
                "login": f"command_{uuid.uuid4().hex[:8]}",
                "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
            }
        )
        self.channel = self.env["agenthub.channel"].create(
            {"name": "Command Channel", "channel_type": FAKE_CHANNEL}
        )
        self.agent = self.env["agenthub.agent"].create(
            {
                "name": "Command Agent",
                "agent_type": FAKE_AGENT,
                "user_id": self.user.id,
                "runtime": "relay",
            }
        )
        self.thread = self.env["agenthub.thread"]._find_or_create(
            self.channel.id, "peer", self.agent.id
        )

    def _command(self, **vals):
        values = {"name": "run_tests", "agent_id": self.agent.id}
        values.update(vals)
        return self.env["agenthub.command"].create(values)

    def test_queued_command_enqueues(self):
        command = self._command(state="queued")
        publish = self.env["agenthub.publish"].search(
            [("event_type", "=", "command.created")], limit=1
        )
        self.assertTrue(publish)
        self.assertEqual(
            publish.event_id, f"odoo:command:{command.id}:command.created"
        )
        self.assertEqual(publish.envelope["route"]["agent_id"], self.agent.id)
        self.assertEqual(
            publish.envelope["payload"]["command_id"],
            command.relay_command_id,
        )

    def test_draft_then_queue(self):
        command = self._command()
        self.assertFalse(
            self.env["agenthub.publish"].search(
                [("event_type", "=", "command.created")]
            )
        )
        command.action_queue()
        self.assertEqual(
            self.env["agenthub.publish"].search_count(
                [("event_type", "=", "command.created")]
            ),
            1,
        )

    def test_command_publish_idempotent(self):
        command = self._command(state="queued")
        command._enqueue_publish()
        self.assertEqual(
            self.env["agenthub.publish"].search_count(
                [("event_type", "=", "command.created")]
            ),
            1,
        )

    def test_thread_reply_payload(self):
        command = self._command(
            state="queued",
            reply_mode="thread",
            thread_id=self.thread.id,
        )
        publish = self.env["agenthub.publish"].search(
            [("event_type", "=", "command.created")], limit=1
        )
        self.assertEqual(
            publish.envelope["payload"]["thread_key"],
            self.thread.relay_thread_key,
        )
        self.assertEqual(publish.envelope["route"]["reply_mode"], "thread")

    def test_thread_reply_without_thread_rejected(self):
        with self.assertRaises(UserError), self.cr.savepoint():
            self._command(state="queued", reply_mode="thread")
