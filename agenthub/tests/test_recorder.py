import uuid
from unittest import mock

from odoo.tests import common, tagged

from .common import selection_value

FAKE_CHANNEL = "test_channel"
FAKE_AGENT = "test_agent"


def _add_selection(test, model, field, value):
    ctx = selection_value(model, field, value)
    ctx.__enter__()
    test.addCleanup(ctx.__exit__, None, None, None)


@tagged("post_install", "-at_install")
class TestRecorder(common.TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Channel = cls.env["agenthub.channel"]
        cls.Agent = cls.env["agenthub.agent"]
        cls.Thread = cls.env["agenthub.thread"]
        cls.Recorder = cls.env["agenthub.recorder"]

    def setUp(self):
        super().setUp()
        _add_selection(self, self.Channel, "channel_type", FAKE_CHANNEL)
        _add_selection(self, self.Agent, "agent_type", FAKE_AGENT)
        self.user = self.env["res.users"].create(
            {
                "name": "Recorder User",
                "login": f"recorder_{uuid.uuid4().hex[:8]}",
                "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
            }
        )
        self.channel = self.Channel.create(
            {"name": "Recorder Channel", "channel_type": FAKE_CHANNEL}
        )
        self.agent = self.Agent.create(
            {
                "name": "Recorder Agent",
                "agent_type": FAKE_AGENT,
                "user_id": self.user.id,
                "runtime": "relay",
            }
        )
        self.thread = self.Thread._find_or_create(
            self.channel.id, "peer", self.agent.id
        )
        self.route = {
            "agent_id": self.agent.id,
            "channel_id": self.channel.id,
            "thread_key": self.thread.relay_thread_key,
            "peer_ref": "peer",
            "user_id": self.user.id,
        }

    def _event(
        self,
        event_type,
        event_id,
        payload,
        *,
        turn_id="turn-1",
        route=None,
        source_type="channel",
        meta=None,
        state="queued",
    ):
        return {
            "event_version": 1,
            "event_id": event_id,
            "event_type": event_type,
            "source": {"type": source_type, "id": "test"},
            "route": route or self.route,
            "turn": {"turn_id": turn_id, "state": state},
            "payload": payload,
            "meta": meta or {"origin": source_type},
        }

    def _user_event(self, event_id="evt-user", **kwargs):
        payload = {
            "message_id": "msg-user",
            "role": "user",
            "content": "hello",
            "final": True,
            "seq": 0,
        }
        return self._event("message.created", event_id, payload, **kwargs)

    def _agent_event(self, event_id="evt-agent", **kwargs):
        payload = {
            "message_id": "msg-agent",
            "role": "assistant",
            "content": "done",
            "stream_id": "s1",
            "seq": 2,
            "final": True,
        }
        return self._event(
            "message.final",
            event_id,
            payload,
            source_type="agent",
            state="running",
            **kwargs,
        )

    def _turn_event(self, event_id="evt-turn", state="completed"):
        return self._event(
            "turn.%s" % state,
            event_id,
            {"state": state},
            source_type="agent",
            state=state,
        )

    def test_user_message_recorded(self):
        self.Recorder._process_event(self._user_event())
        message = self.env["mail.message"].search(
            [("agenthub_relay_message_id", "=", "msg-user")], limit=1
        )
        self.assertTrue(message)
        self.assertEqual(message.agenthub_role, "user")
        self.assertIn("hello", message.body)
        self.assertEqual(message.model, "agenthub.thread")
        self.assertEqual(message.res_id, self.thread.id)
        turn = message.agenthub_turn_id
        self.assertEqual(turn.relay_turn_id, "turn-1")
        self.assertEqual(turn.inbound_message_id, message)

    def test_message_idempotent(self):
        self.Recorder._process_event(self._user_event(event_id="evt-1"))
        self.Recorder._process_event(self._user_event(event_id="evt-2"))
        self.assertEqual(
            self.env["mail.message"].search_count(
                [("agenthub_relay_message_id", "=", "msg-user")]
            ),
            1,
        )

    def test_agent_message_and_stream(self):
        self.Recorder._process_event(self._user_event())
        self.Recorder._process_event(self._agent_event(event_id="evt-a"))
        message = self.env["mail.message"].search(
            [("agenthub_relay_message_id", "=", "msg-agent")], limit=1
        )
        self.assertTrue(message)
        self.assertEqual(message.agenthub_role, "assistant")
        self.assertEqual(message.agenthub_stream_id, "s1")
        self.assertIn("done", message.body)
        self.Recorder._process_event(self._agent_event(event_id="evt-b"))
        self.assertEqual(
            self.env["mail.message"].search_count(
                [("agenthub_relay_message_id", "=", "msg-agent")]
            ),
            1,
        )

    def test_turn_completion(self):
        self.Recorder._process_event(self._user_event())
        turn = self.env["agenthub.turn"].search(
            [("relay_turn_id", "=", "turn-1")], limit=1
        )
        self.assertTrue(turn.is_active)
        self.Recorder._process_event(self._turn_event())
        self.assertEqual(turn.state, "completed")
        self.assertFalse(turn.is_active)

    def test_delivery_audit(self):
        self.Recorder._process_event(self._user_event())
        event = self._event(
            "delivery.acked",
            "evt-dlv",
            {"delivery_id": "dlv-1", "leg": "to_agent", "state": "done"},
        )
        self.Recorder._process_event(event)
        delivery = self.env["agenthub.delivery"].search(
            [("relay_delivery_id", "=", "dlv-1")], limit=1
        )
        self.assertTrue(delivery)
        self.assertEqual(delivery.state, "done")
        self.assertTrue(delivery.sent_at)

    def test_presence_updates_agent(self):
        event = {
            "event_version": 1,
            "event_id": "evt-presence",
            "event_type": "presence.changed",
            "source": {"type": "relay", "id": "test"},
            "payload": {"agent_id": self.agent.id, "state": "online"},
            "meta": {"origin": "system"},
        }
        self.Recorder._process_event(event)
        self.assertEqual(self.agent.state, "online")
        self.assertTrue(self.agent.last_seen)

    def test_discuss_projection(self):
        discuss = self.env["discuss.channel"].create({"name": "Recorder DM"})
        thread_key = "discuss.channel:%s" % discuss.id
        self.Thread.create(
            {
                "name": discuss.name,
                "peer_ref": thread_key,
                "agent_id": self.agent.id,
                "relay_thread_key": thread_key,
                "discuss_channel_id": discuss.id,
            }
        )
        route = {
            "agent_id": self.agent.id,
            "thread_key": thread_key,
            "peer_ref": thread_key,
            "user_id": self.user.id,
        }
        event = self._agent_event(event_id="evt-dm", route=route)
        self.Recorder._process_event(event)
        message = self.env["mail.message"].search(
            [
                ("model", "=", "discuss.channel"),
                ("res_id", "=", discuss.id),
                ("agenthub_relay_message_id", "=", "msg-agent"),
            ],
            limit=1,
        )
        self.assertTrue(message)
        self.assertEqual(message.author_id, self.agent.user_id.partner_id)
        self.assertEqual(message.agenthub_role, "assistant")

    def test_origin_record_link(self):
        discuss = self.env["discuss.channel"].create({"name": "Origin DM"})
        thread_key = "discuss.channel:%s" % discuss.id
        self.Thread.create(
            {
                "name": discuss.name,
                "peer_ref": thread_key,
                "agent_id": self.agent.id,
                "relay_thread_key": thread_key,
                "discuss_channel_id": discuss.id,
            }
        )
        existing = discuss.message_post(
            body="from odoo",
            author_id=self.user.partner_id.id,
            message_type="comment",
        )
        route = {
            "agent_id": self.agent.id,
            "thread_key": thread_key,
            "peer_ref": thread_key,
            "user_id": self.user.id,
        }
        event = self._user_event(
            event_id="evt-origin",
            route=route,
            meta={
                "origin": "odoo",
                "origin_record_id": "mail.message,%s" % existing.id,
            },
        )
        event["payload"]["message_id"] = "msg-origin"
        before = self.env["mail.message"].search_count(
            [("model", "=", "discuss.channel"), ("res_id", "=", discuss.id)]
        )
        self.Recorder._process_event(event)
        after = self.env["mail.message"].search_count(
            [("model", "=", "discuss.channel"), ("res_id", "=", discuss.id)]
        )
        self.assertEqual(before, after)
        self.assertEqual(existing.agenthub_relay_message_id, "msg-origin")
        self.assertEqual(existing.agenthub_role, "user")

    def test_pull_once(self):
        params = self.env["ir.config_parameter"].sudo()
        params.set_param("agenthub.relay_url", "http://relay.test")
        params.set_param("agenthub.relay_recorder_token", "token")
        event = self._user_event()

        class FakeResponse:
            def raise_for_status(self):
                return None

            def json(self):
                return {
                    "events": [event],
                    "next_cursor": 1,
                    "lag_seconds": 0.2,
                }

        Cursor = self.env["agenthub.record.cursor"]
        with mock.patch(
            "odoo.addons.agenthub.models.agenthub_record_cursor.requests.get",
            return_value=FakeResponse(),
        ) as get, mock.patch(
            "odoo.addons.agenthub.models.agenthub_record_cursor.requests.post"
        ) as post:
            processed = Cursor._pull_once()
        self.assertEqual(processed, 1)
        record = Cursor._get("relay")
        self.assertEqual(record.cursor, "1")
        self.assertEqual(record.lag_seconds, 0.2)
        get.assert_called_once()
        post.assert_called_once()
        self.assertTrue(
            self.env["mail.message"].search(
                [("agenthub_relay_message_id", "=", "msg-user")]
            )
        )
