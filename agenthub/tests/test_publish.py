from unittest import mock

from odoo.addons.agenthub.models.agenthub_publish import PublishError
from odoo.tests import common, tagged


@tagged("post_install", "-at_install")
class TestPublishOutbox(common.TransactionCase):
    def setUp(self):
        super().setUp()
        self.Publish = self.env["agenthub.publish"]

    def _enqueue(self, event_id="evt-1"):
        return self.Publish._enqueue(
            "message.created",
            {"role": "user", "content": "hello"},
            event_id=event_id,
            route={"agent_id": 1, "thread_key": "thread:1"},
            turn={"turn_id": "turn-1", "seq": 0},
            meta={"origin": "odoo", "origin_record_id": "mail.message,1"},
        )

    def test_enqueue_builds_envelope(self):
        event = self._enqueue()
        self.assertEqual(event.state, "pending")
        self.assertEqual(event.envelope["event_version"], 1)
        self.assertEqual(event.envelope["event_id"], "evt-1")
        self.assertEqual(event.envelope["event_type"], "message.created")
        self.assertEqual(event.envelope["source"]["type"], "odoo")
        self.assertEqual(event.envelope["payload"]["role"], "user")
        self.assertEqual(event.envelope["meta"]["origin"], "odoo")

    def test_enqueue_is_idempotent(self):
        first = self._enqueue("evt-1")
        second = self._enqueue("evt-1")
        self.assertEqual(first, second)
        self.assertEqual(
            self.Publish.search_count([("event_id", "=", "evt-1")]), 1
        )

    def test_process_success(self):
        event = self._enqueue()
        with mock.patch.object(
            type(self.Publish), "_send_envelope", return_value=True
        ):
            processed = self.Publish._process_pending()
        self.assertEqual(processed, 1)
        self.assertEqual(event.state, "sent")
        self.assertTrue(event.sent_at)

    def test_process_unconfigured_is_retryable(self):
        event = self._enqueue()
        with mock.patch.object(
            type(self.Publish), "_send_envelope", return_value=None
        ):
            processed = self.Publish._process_pending()
        self.assertEqual(processed, 1)
        self.assertEqual(event.state, "failed")
        self.assertEqual(event.attempt, 1)
        self.assertTrue(event.next_retry)

    def test_process_exception_is_retryable(self):
        event = self._enqueue()
        with mock.patch.object(
            type(self.Publish),
            "_send_envelope",
            side_effect=RuntimeError("boom"),
        ):
            self.Publish._process_pending()
        self.assertEqual(event.state, "failed")
        self.assertEqual(event.attempt, 1)
        self.assertIn("boom", event.last_error)

    def test_terminal_failure_marks_dead(self):
        event = self._enqueue()
        with mock.patch.object(
            type(self.Publish),
            "_send_envelope",
            side_effect=PublishError("rejected", retryable=False),
        ):
            self.Publish._process_pending()
        self.assertEqual(event.state, "dead")
        self.assertFalse(event.next_retry)
