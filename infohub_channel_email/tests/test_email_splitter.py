import email as email_lib
import json
from unittest import mock

from odoo.tests.common import TransactionCase, tagged

from odoo.addons.infohub.tests.common import selection_value
from odoo.addons.infohub_channel_email.models.infohub_email_message import SPLITTER_CODE


@tagged("post_install", "-at_install")
class TestEmailSplitter(TransactionCase):
    """Digest emails split into individual items by the email splitter agent."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Channel = cls.env["infohub.channel"]
        cls.Message = cls.env["infohub.email.message"]
        cls.Item = cls.env["infohub.item"]
        cls.agent = cls.env["llm.agent"].search([("code", "=", SPLITTER_CODE)])
        cls._open_service_selection()
        cls._configure_agent()

    @classmethod
    def _open_service_selection(cls):
        """``llm.provider.service`` is contributed by provider addons this
        module does not install; stub a value so a provider can be created."""
        ctx = selection_value(cls.env["llm.provider"], "service", "split_test_service")
        ctx.__enter__()
        cls.addClassCleanup(ctx.__exit__, None, None, None)

    @classmethod
    def _configure_agent(cls):
        provider = cls.env["llm.provider"].create(
            {"name": "Test Provider", "service": "split_test_service"}
        )
        model = cls.env["llm.model"].create(
            {"name": "test-model", "provider_id": provider.id}
        )
        cls.agent.write({"provider_id": provider.id, "model_id": model.id})

    def _channel(self, split_items=True, address="news@example.com", **vals):
        return self.Channel.create(
            {
                "name": "Newsletter",
                "channel_type": "email",
                "email_to": address,
                "split_items": split_items,
                **vals,
            }
        )

    def _relay(self, channel):
        return self.Message.create(
            {
                "channel_id": channel.id,
                "subject": "Weekly Digest",
                "email_from": "editor@nature.com",
                "date": "2026-09-16 10:00:00",
                "body": "<p>Article one.</p><p>Article two.</p>",
            }
        )

    def _invoke_returning(self, payload=None, error=None):
        """Patch ``llm.agent.invoke`` with a canned answer."""
        result = {"result": payload, "error": error, "thread_id": None}
        return mock.patch.object(
            type(self.env["llm.agent"]), "invoke", return_value=result
        )

    @staticmethod
    def _mime(subject="Weekly Digest", sender="editor@nature.com", to="news@example.com"):
        message = email_lib.message.EmailMessage()
        message["Subject"] = subject
        message["From"] = sender
        message["To"] = to
        message["Date"] = "Wed, 16 Sep 2026 10:00:00 +0000"
        message["Message-Id"] = "<digest-split@nature.com>"
        message.set_content("Latest research highlights.")
        return message

    def _deliver(self, message):
        return self.Message.message_process(
            self.Message._name, message.as_bytes(), save_original=False
        )

    # -- scheduling ------------------------------------------------------

    def test_split_channel_queues_instead_of_syncing(self):
        channel = self._channel(split_items=True)
        self._deliver(self._mime())

        relay = self.Message.search([("channel_id", "=", channel.id)])
        self.assertEqual(len(relay), 1)
        self.assertEqual(relay.state, "queued")
        self.assertEqual(
            self.Item.search_count([("channel_id", "=", channel.id)]), 0
        )
        jobs = self.env["queue.job"].search(
            [("identity_key", "=", f"infohub-email-split-{relay.id}")]
        )
        self.assertEqual(len(jobs), 1)

    def test_split_without_configured_agent_falls_back(self):
        channel = self._channel(split_items=True)
        self.agent.write({"provider_id": False, "model_id": False})
        self._deliver(self._mime())

        relay = self.Message.search([("channel_id", "=", channel.id)])
        self.assertEqual(relay.state, "processed")
        self.assertEqual(
            self.Item.search_count([("channel_id", "=", channel.id)]), 1
        )

    # -- job -------------------------------------------------------------

    def test_job_splits_digest_into_items(self):
        channel = self._channel(split_items=True)
        relay = self._relay(channel)
        answer = json.dumps(
            {
                "items": [
                    {"title": "First story", "summary": "Body one.", "url": "https://nature.com/1"},
                    {"title": "Second story", "summary": "Body two.", "url": ""},
                    {"title": "Third story", "summary": "Body three.", "url": "https://nature.com/3"},
                ]
            }
        )
        with self._invoke_returning(answer) as patched:
            relay._job_split_and_ingest()

        items = self.Item.search([("channel_id", "=", channel.id)])
        self.assertEqual(len(items), 3)
        self.assertEqual(
            set(items.mapped("title")),
            {"First story", "Second story", "Third story"},
        )
        first = items.filtered(lambda i: i.title == "First story")
        self.assertIn("Body one.", first.content_text)
        self.assertEqual(relay.state, "processed")

        # The agent is fed the plain-text body, not HTML.
        query = patched.call_args[0][0]
        self.assertIn("Article one", query)
        self.assertTrue(patched.call_args[1].get("new_cursor") is False)

    def test_job_falls_back_to_single_item_when_no_items(self):
        channel = self._channel(split_items=True)
        relay = self._relay(channel)
        with self._invoke_returning(json.dumps({"items": []})):
            relay._job_split_and_ingest()

        items = self.Item.search([("channel_id", "=", channel.id)])
        self.assertEqual(len(items), 1)
        self.assertEqual(relay.state, "processed")

    def test_job_records_agent_error(self):
        channel = self._channel(split_items=True)
        relay = self._relay(channel)
        with self._invoke_returning(error="boom"):
            relay._job_split_and_ingest()

        self.assertEqual(relay.state, "error")
        self.assertEqual(relay.error_message, "boom")

    def test_job_records_malformed_answer(self):
        channel = self._channel(split_items=True)
        relay = self._relay(channel)
        with self._invoke_returning("I cannot help with that."):
            relay._job_split_and_ingest()

        self.assertEqual(relay.state, "error")
        self.assertTrue(relay.error_message)

    def test_job_reprocessing_is_idempotent(self):
        channel = self._channel(split_items=True)
        relay = self._relay(channel)
        answer = json.dumps(
            {
                "items": [
                    {"title": "First story", "summary": "Body one.", "url": ""},
                    {"title": "Second story", "summary": "Body two.", "url": ""},
                ]
            }
        )
        with self._invoke_returning(answer):
            relay._job_split_and_ingest()
            relay._job_split_and_ingest()

        self.assertEqual(
            self.Item.search_count([("channel_id", "=", channel.id)]), 2
        )
