"""Tests for agenthub adapter dispatch.

``agenthub.channel.send`` and ``agenthub.agent.reply`` resolve their adapter by
``_usage == channel_type`` / ``_usage == agent_type``. The base addon ships no
concrete type, so the tests register stub components in an isolated registry
and add a fake Selection value for their duration.
"""

from odoo.exceptions import UserError
from odoo.tests import tagged

from odoo.addons.component.core import Component
from odoo.addons.component.tests.common import TransactionComponentRegistryCase

from .common import selection_value

FAKE_CHANNEL = "test_channel"
FAKE_AGENT = "test_agent"


class _DispatchCase(TransactionComponentRegistryCase):
    """Shared: isolated registry + the abstract base components loaded."""

    def setUp(self):
        super().setUp()
        self._setup_registry(self)
        self.addCleanup(self._teardown_registry, self)
        self._load_module_components("agenthub")

    def _add_selection(self, model, field, value):
        ctx = selection_value(model, field, value)
        ctx.__enter__()
        self.addCleanup(ctx.__exit__, None, None, None)


@tagged("post_install", "-at_install")
class TestChannelDispatch(_DispatchCase):
    def setUp(self):
        super().setUp()
        Channel = self.env["agenthub.channel"]
        self._add_selection(Channel, "channel_type", FAKE_CHANNEL)
        # Created after _setup_registry so the record's env carries the
        # components_registry context key that work_on() propagates.
        self.channel = Channel.create(
            {"name": "probe", "channel_type": FAKE_CHANNEL}
        )

    def _build_stub(self, usage, name):
        class _Stub(Component):
            _name = name
            _inherit = "agenthub.channel.adapter"
            _usage = usage

            def send(self, channel, message):
                return ("send", channel, message)

        self._build_components(_Stub)
        return _Stub

    def test_no_adapter_raises_user_error(self):
        with self.assertRaises(UserError):
            self.channel.send(object())

    def test_dispatch_calls_the_adapter(self):
        self._build_stub(FAKE_CHANNEL, "stub.channel.adapter")
        marker = object()
        self.assertEqual(
            self.channel.send(marker), ("send", self.channel, marker)
        )

    def test_adapter_of_another_type_is_not_used(self):
        self._build_stub("other_type", "stub.other.adapter")
        with self.assertRaises(UserError):
            self.channel.send(object())


@tagged("post_install", "-at_install")
class TestAgentDispatch(_DispatchCase):
    def setUp(self):
        super().setUp()
        Agent = self.env["agenthub.agent"]
        self._add_selection(Agent, "agent_type", FAKE_AGENT)
        self.agent = Agent.create({"name": "probe", "agent_type": FAKE_AGENT})

    def _build_stub(self, usage, name):
        class _Stub(Component):
            _name = name
            _inherit = "agenthub.agent.adapter"
            _usage = usage

            def reply(self, agent, message):
                return ("reply", agent, message)

        self._build_components(_Stub)
        return _Stub

    def test_no_adapter_raises_user_error(self):
        with self.assertRaises(UserError):
            self.agent.reply(object())

    def test_dispatch_calls_the_adapter(self):
        self._build_stub(FAKE_AGENT, "stub.agent.adapter")
        marker = object()
        self.assertEqual(
            self.agent.reply(marker), ("reply", self.agent, marker)
        )

    def test_adapter_of_another_type_is_not_used(self):
        self._build_stub("other_type", "stub.other.adapter")
        with self.assertRaises(UserError):
            self.agent.reply(object())
