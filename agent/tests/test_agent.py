# Copyright 2026 Rui
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

"""Model and component-resolution tests for the ``agent`` core."""

from unittest import mock

from psycopg2 import IntegrityError

from odoo.exceptions import UserError

from .common import AgentCase, StubAdapter


class TestAgentModel(AgentCase):
    def test_create_defaults(self):
        agent = self._create_agent()
        self.assertEqual(agent.runner, "react")
        self.assertEqual(agent.tool_calls_max, 20)
        self.assertEqual(agent.context_limit, 25)
        self.assertFalse(agent.use_streaming)
        self.assertTrue(agent.active)

    def test_code_unique(self):
        self._create_agent(code="dup_code")
        with self.assertRaises(IntegrityError):
            with self.env.cr.savepoint():
                self._create_agent(code="dup_code")

    def test_runner_resolution(self):
        agent = self._create_agent()
        runner = agent._get_runner()
        self.assertEqual(runner._name, "agent.runner.react")

    def test_context_builders_ordered(self):
        agent = self._create_agent()
        builders = agent._get_context_builders()
        names = [b._name for b in builders]
        self.assertIn("agent.context.builder.system", names)
        self.assertIn("agent.context.builder.tools", names)
        # system (priority 10) must come before tools (priority 20)
        self.assertLess(
            names.index("agent.context.builder.system"),
            names.index("agent.context.builder.tools"),
        )

    def test_provider_adapter_fallback(self):
        adapter = self.provider._get_agent_adapter()
        self.assertEqual(adapter._name, "agent.provider.adapter.generic")

    def test_tool_executor_fallback(self):
        executor = self.tool._get_tool_executor()
        self.assertEqual(executor._name, "agent.tool.executor.generic")


class TestGenericAdapter(AgentCase):
    def test_generic_adapter_delegates_chat(self):
        adapter = self.provider._get_agent_adapter()
        with mock.patch.object(
            type(self.provider), "chat", return_value={"content": "x"}
        ) as chat_mock:
            result = adapter.chat(self.model, self.env["mail.message"])
        chat_mock.assert_called_once()
        self.assertEqual(result, {"content": "x"})

    def test_generic_executor_delegates_execute(self):
        executor = self.tool._get_tool_executor()
        with mock.patch.object(
            type(self.tool), "execute", return_value={"ok": True}
        ) as exec_mock:
            result = executor.execute(self.tool, {"a": 1})
        exec_mock.assert_called_once_with({"a": 1})
        self.assertEqual(result, {"ok": True})


class TestThreadBridge(AgentCase):
    def test_set_agent_syncs_fields(self):
        agent = self._create_agent(tool_ids=[(6, 0, [self.tool.id])])
        thread = self._create_thread(agent)
        self.assertEqual(thread.agent_id, agent)
        self.assertEqual(thread.provider_id, self.provider)
        self.assertEqual(thread.model_id, self.model)
        self.assertEqual(thread.tool_ids, self.tool)

    def test_generate_messages_requires_agent(self):
        thread = self.env["llm.thread"].create(
            {
                "name": "No Agent",
                "provider_id": self.provider.id,
                "model_id": self.model.id,
            }
        )
        with self.assertRaises(UserError):
            list(thread.generate(user_message_body="hi"))


class TestInvoke(AgentCase):
    def test_invoke_returns_result(self):
        agent = self._create_agent()
        stub = StubAdapter([{"content": "the answer"}])
        self._patch_adapter(stub)

        result = agent.invoke("hi", new_cursor=False)

        self.assertEqual(result["result"], "the answer")
        self.assertIsNone(result["error"])
        self.assertTrue(result["thread_id"])
        self.assertEqual(len(stub.calls), 1)
        self.assertIs(stub.calls[0]["stream"], False)

    def test_invoke_by_code_not_found(self):
        result = self.env["agent.agent"].invoke_agent("nope", "hi")
        self.assertIsNone(result["result"])
        self.assertIn("not found", result["error"])
