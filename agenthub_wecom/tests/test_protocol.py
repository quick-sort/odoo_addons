from odoo.tests import common, tagged

from ..services import aibot


@tagged("post_install", "-at_install")
class TestAibotProtocol(common.TransactionCase):
    def test_authenticate_success(self):
        frame = {
            "headers": {"req_id": "subscribe_1"},
            "body": {"bot_id": "bot", "secret": "s3cret"},
        }
        resp = aibot.authenticate(frame, "s3cret")
        self.assertEqual(resp["errcode"], 0)
        self.assertEqual(resp["headers"]["req_id"], "subscribe_1")

    def test_authenticate_wrong_secret(self):
        frame = {
            "headers": {"req_id": "subscribe_1"},
            "body": {"bot_id": "bot", "secret": "wrong"},
        }
        resp = aibot.authenticate(frame, "s3cret")
        self.assertNotEqual(resp["errcode"], 0)

    def test_authenticate_missing_expected_secret(self):
        frame = {
            "headers": {"req_id": "subscribe_1"},
            "body": {"bot_id": "bot", "secret": "s3cret"},
        }
        resp = aibot.authenticate(frame, "")
        self.assertNotEqual(resp["errcode"], 0)

    def test_ping_response(self):
        frame = {"headers": {"req_id": "ping_1"}}
        self.assertEqual(
            aibot.ping_response(frame),
            {"headers": {"req_id": "ping_1"}, "errcode": 0, "errmsg": "ok"},
        )

    def test_acknowledge(self):
        frame = {"headers": {"req_id": "respond_1"}}
        self.assertEqual(aibot.acknowledge(frame)["headers"]["req_id"], "respond_1")

    def test_build_message_callback(self):
        frame = aibot.build_message_callback("m1", "bot", "single", "u1", "hello")
        self.assertEqual(frame["cmd"], "aibot_msg_callback")
        self.assertEqual(frame["headers"]["req_id"], "m1")
        self.assertEqual(frame["body"]["msgid"], "m1")
        self.assertEqual(frame["body"]["from"]["userid"], "u1")
        self.assertEqual(frame["body"]["text"]["content"], "hello")

    def test_build_disconnected_event(self):
        frame = aibot.build_disconnected_event("m1", "bot")
        self.assertEqual(frame["cmd"], "aibot_event_callback")
        self.assertEqual(frame["body"]["event"]["eventtype"], "disconnected_event")

    def test_extract_inbound(self):
        frame = {
            "headers": {"req_id": "q1"},
            "body": {
                "msgtype": "stream",
                "stream": {"id": "s1", "finish": True, "content": "hi"},
            },
        }
        result = aibot.extract_inbound(frame)
        self.assertEqual(result["reply_to_external_id"], "q1")
        self.assertEqual(result["external_id"], "s1")
        self.assertEqual(result["text"], "hi")
        self.assertTrue(result["finished"])
