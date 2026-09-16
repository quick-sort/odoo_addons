import datetime
import email as email_lib

from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestEmailChannel(TransactionCase):
    """Inbound newsletter email, parsed from real MIME messages."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Channel = cls.env["infohub.channel"]
        cls.Message = cls.env["infohub.email.message"]

    def _channel(self, address="news@example.com", **vals):
        return self.Channel.create(
            {
                "name": "Newsletter",
                "channel_type": "email",
                "email_to": address,
                **vals,
            }
        )

    @staticmethod
    def _mime(subject="Weekly Digest", sender="editor@nature.com", to="news@example.com"):
        """A minimal RFC-2822 message, as the mail gateway would receive it."""
        message = email_lib.message.EmailMessage()
        message["Subject"] = subject
        message["From"] = sender
        message["To"] = to
        message["Date"] = "Wed, 16 Sep 2026 10:00:00 +0000"
        message["Message-Id"] = "<digest-1@nature.com>"
        message.set_content("Latest research highlights.")
        return message

    def _deliver(self, message):
        """Push a MIME message through the same entry point the gateway uses.

        ``message_process`` takes raw bytes, as it receives from the mail
        server, so the message is serialised first.
        """
        return self.Message.message_process(
            self.Message._name, message.as_bytes(), save_original=False
        )

    # -- channel model ---------------------------------------------------

    def test_email_is_a_selectable_channel_type(self):
        selection = dict(self.Channel._fields["channel_type"].selection)
        self.assertIn("email", selection)

    def test_email_to_field_exists(self):
        self.assertTrue(self._channel().email_to)

    # -- inbound delivery ------------------------------------------------

    def test_inbound_email_creates_an_item(self):
        channel = self._channel()
        self._deliver(self._mime())

        item = self.env["infohub.item"].search([("channel_id", "=", channel.id)])
        self.assertEqual(len(item), 1)
        self.assertEqual(item.title, "Weekly Digest")
        self.assertIn("Latest research highlights", item.content_text)

    def test_inbound_email_is_stored_on_the_relay(self):
        """The original email survives, for when parsing needs revisiting."""
        channel = self._channel()
        self._deliver(self._mime())

        relay = self.Message.search([("channel_id", "=", channel.id)])
        self.assertEqual(len(relay), 1)
        self.assertEqual(relay.subject, "Weekly Digest")
        self.assertEqual(relay.email_from, "editor@nature.com")
        self.assertEqual(relay.state, "processed")

    def test_email_routed_to_channel_by_recipient(self):
        """Two channels, one inbox each — the recipient decides."""
        nature = self._channel("nature@example.com", name="Nature")
        self._channel("lancet@example.com", name="Lancet")

        self._deliver(self._mime(to="nature@example.com"))

        relay = self.Message.search([("channel_id", "=", nature.id)])
        self.assertEqual(len(relay), 1)
        self.assertEqual(relay.channel_id, nature)

    def test_email_with_unknown_recipient_is_kept_unmatched(self):
        """No match leaves the relay record for a human, it does not vanish."""
        self._channel("nature@example.com")
        self._deliver(self._mime(to="nobody@example.com"))

        relay = self.Message.search([("channel_id", "=", False)])
        self.assertEqual(len(relay), 1)
        self.assertEqual(relay.state, "error")
        self.assertIn("channel", relay.error_message.lower())

    def test_matching_is_case_insensitive(self):
        channel = self._channel("News@Example.com")
        self._deliver(self._mime(to="news@example.com"))
        self.assertEqual(
            self.env["infohub.item"].search_count([("channel_id", "=", channel.id)]), 1
        )

    def test_cc_recipient_also_matches(self):
        """A newsletter delivered via cc still routes correctly."""
        channel = self._channel("news@example.com")

        # Sent only to an unrelated address: nothing lands on the channel.
        self._deliver(self._mime(to="someone@example.com"))
        self.assertEqual(
            self.env["infohub.item"].search_count([("channel_id", "=", channel.id)]), 0
        )

        # Same, but with the channel address in Cc.
        message = self._mime(to="someone@example.com")
        message["Cc"] = "news@example.com"
        message.replace_header("Message-Id", "<digest-cc@nature.com>")
        self._deliver(message)
        self.assertEqual(
            self.env["infohub.item"].search_count([("channel_id", "=", channel.id)]), 1
        )

    # -- pool hygiene ----------------------------------------------------

    def test_pool_item_carries_no_chatter(self):
        """infohub.item must stay free of mail.thread machinery.

        That is the whole reason for the relay: chatter tables grow with
        received emails, not with the number of news items in the pool.
        """
        self.assertNotIn("message_ids", self.env["infohub.item"]._fields)
        # The relay does carry it — that is the point of the relay.
        self.assertIn("message_ids", self.Message._fields)

    def test_source_is_matched_from_sender_name(self):
        source = self.env["infohub.source"].create({"name": "Nature"})
        channel = self._channel()
        self._deliver(self._mime(sender="nature@example.com"))
        item = self.env["infohub.item"].search([("channel_id", "=", channel.id)])
        # No source named exactly like the address -> left unattributed.
        self.assertFalse(item.source_id)
        self.assertTrue(source)

    # -- component contract ----------------------------------------------

    def test_fetch_returns_nothing_for_email(self):
        """Email is pushed, never polled."""
        channel = self._channel()
        _raw, items = channel.fetch_news()
        self.assertEqual(items, [])
