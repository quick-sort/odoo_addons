from odoo.tests import common, tagged

from ..components.agent import AgenthubAgentOpenclaw


class FakeMessage:
    def __init__(self, content, body=""):
        self.agenthub_content = content
        self.body = body


@tagged("post_install", "-at_install")
class TestOpenclawAgent(common.TransactionCase):
    def test_agent_type_has_openclaw(self):
        values = dict(self.env["agenthub.agent"]._fields["agent_type"].selection)
        self.assertIn("openclaw", values)

    def _adapter(self):
        return AgenthubAgentOpenclaw(object.__new__(AgenthubAgentOpenclaw))

    def test_reply_strips_think_from_raw_content(self):
        agent = self.env["agenthub.agent"]
        message = FakeMessage("<think>reasoning</think>answer")
        self.assertEqual(self._adapter().reply(agent, message), "answer")

    def test_reply_falls_back_to_body(self):
        agent = self.env["agenthub.agent"]
        message = FakeMessage("", "<p>hello</p>")
        self.assertEqual(self._adapter().reply(agent, message), "hello")
