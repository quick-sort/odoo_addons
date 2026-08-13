# Copyright 2026 Rui
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

"""Shared fixtures for the agent tests.

No concrete provider addon (``llm_openai`` / ``llm_anthropic``) is installed in
this test DB, so the ``llm.provider.service`` selection is empty by default. We
register a fake ``test`` service via a class patch, mirroring how ``llm_tool``
tests patch ``_get_available_implementations``.
"""

from unittest import mock

from odoo.addons.component.tests.common import TransactionComponentCase


class StubAdapter:
    """In-memory ``agent.provider.adapter``.

    ``responses`` are consumed in order; an entry that is an ``Exception``
    instance is raised. ``calls`` records the kwargs of each ``chat``.
    """

    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def chat(self, model, **kwargs):
        self.calls.append(kwargs)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class StubExecutor:
    """In-memory ``agent.tool.executor`` returning a fixed result."""

    def __init__(self, result=None):
        self.result = result
        self.calls = []

    def execute(self, tool, parameters, session=None):
        self.calls.append((tool, parameters, session))
        return self.result if self.result is not None else {"echoed": parameters}


class AgentCase(TransactionComponentCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls._patchers = []

        service_patcher = mock.patch.object(
            type(cls.env["llm.provider"]),
            "_get_available_services",
            lambda self: [("test", "Test")],
        )
        service_patcher.start()
        cls._patchers.append(service_patcher)

        cls.provider = cls.env["llm.provider"].create(
            {"name": "Test Provider", "service": "test"}
        )
        cls.model = cls.env["llm.model"].create(
            {"name": "test-model", "provider_id": cls.provider.id}
        )
        cls.tool = cls.env["llm.tool"].create(
            {
                "name": "echo",
                "description": "Echo the given arguments.",
                "implementation": "function",
            }
        )

    @classmethod
    def tearDownClass(cls):
        for patcher in cls._patchers:
            patcher.stop()
        super().tearDownClass()

    # -- helpers ---------------------------------------------------------

    def _create_agent(self, **kw):
        vals = {
            "name": "Test Agent",
            "code": "test_agent_%s" % self.env["agent.agent"].search_count([]),
            "provider_id": self.provider.id,
            "model_id": self.model.id,
        }
        vals.update(kw)
        return self.env["agent.agent"].create(vals)

    def _create_thread(self, agent):
        thread = self.env["llm.thread"].create(
            {
                "name": "Test Thread",
                "provider_id": self.provider.id,
                "model_id": self.model.id,
            }
        )
        thread.set_agent(agent.id)
        return thread

    def _post_user_message(self, thread, body="hello"):
        return thread.message_post(
            body=body,
            llm_role="user",
            author_id=self.env.user.partner_id.id,
        )

    def _messages(self, thread, role):
        return self.env["mail.message"].search(
            [
                ("model", "=", "llm.thread"),
                ("res_id", "=", thread.id),
                ("llm_role", "=", role),
            ],
            order="id ASC",
        )

    def _patch_adapter(self, adapter):
        patcher = mock.patch.object(
            type(self.env["llm.provider"]),
            "_get_agent_adapter",
            lambda self: adapter,
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        return adapter

    def _patch_executor(self, executor):
        patcher = mock.patch.object(
            type(self.env["llm.tool"]),
            "_get_tool_executor",
            lambda self: executor,
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        return executor
