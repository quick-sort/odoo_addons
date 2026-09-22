from odoo.exceptions import UserError
from odoo.tests import common, tagged

from ..components.channel import AgenthubChannelWecom
from ..services.aibot import registry
from .test_registry import FakeConnection


@tagged("post_install", "-at_install")
class TestWecomChannelModel(common.TransactionCase):
    def test_channel_type_has_wecom(self):
        values = dict(
            self.env["agenthub.channel"]._fields["channel_type"].selection
        )
        self.assertIn("wecom", values)

    def test_bot_config_fields(self):
        fields = self.env["agenthub.channel"]._fields
        self.assertIn("bot_id", fields)
        self.assertIn("secret", fields)


@tagged("post_install", "-at_install")
class TestWecomChannelSend(common.TransactionCase):
    def _make_channel(self, bot_id="bot-1"):
        return self.env["agenthub.channel"].create(
            {"name": "wecom", "channel_type": "wecom", "bot_id": bot_id}
        )

    def _make_message(self, body="hello"):
        return self.env["mail.message"].create({"body": body})

    def _adapter(self):
        return AgenthubChannelWecom(object.__new__(AgenthubChannelWecom))

    def test_send_delivers_to_registered_connection(self):
        channel = self._make_channel()
        message = self._make_message()
        conn = FakeConnection()
        registry.register("bot-1", conn)
        self.addCleanup(registry.unregister, "bot-1", conn)

        self._adapter().send(channel, message)

        self.assertEqual(len(conn.sent), 1)
        self.assertEqual(conn.sent[0]["body"]["text"]["content"], "hello")
        self.assertEqual(conn.sent[0]["cmd"], "aibot_msg_callback")

    def test_send_raises_when_not_connected(self):
        channel = self._make_channel()
        message = self._make_message()

        with self.assertRaises(UserError):
            self._adapter().send(channel, message)
