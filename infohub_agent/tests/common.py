"""Shared helpers for the InfoHub agent test suite."""

from odoo.addons.infohub.tests.common import selection_value

# Channel types and provider services are contributed by addons this module
# does not depend on. Neither is under test here, so both get a stub value.
STUB_CHANNEL_TYPE = "agent_test_stub"
STUB_SERVICE = "agent_test_service"


class StubSelectionMixin:
    """Enter the stubbed selection values for the duration of a test class."""

    @classmethod
    def _open_selections(cls):
        ctxs = [
            selection_value(
                cls.env["infohub.channel"], "channel_type", STUB_CHANNEL_TYPE
            ),
            selection_value(cls.env["llm.provider"], "service", STUB_SERVICE),
        ]
        for ctx in ctxs:
            ctx.__enter__()
            cls.addClassCleanup(ctx.__exit__, None, None, None)

    @classmethod
    def _make_channel(cls, name="Test"):
        return cls.env["infohub.channel"].create(
            {"name": name, "channel_type": STUB_CHANNEL_TYPE}
        )

    @classmethod
    def _make_provider(cls):
        return cls.env["llm.provider"].create(
            {"name": "Test Provider", "service": STUB_SERVICE}
        )
