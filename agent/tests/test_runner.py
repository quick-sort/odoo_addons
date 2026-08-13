# Copyright 2026 Rui
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

"""Runner loop tests: drive the ReAct runner with stubbed adapters/executors."""

from .common import AgentCase, StubAdapter, StubExecutor


def _tool_call(name, arguments='{"x": 1}'):
    return {
        "id": "call_1",
        "type": "function",
        "function": {"name": name, "arguments": arguments},
    }


class TestRunner(AgentCase):
    def _run(self, agent, thread, user_message):
        runner = agent._get_runner()
        events = list(runner.run(agent, thread, user_message))
        return events

    def test_single_response_no_tools(self):
        agent = self._create_agent()
        thread = self._create_thread(agent)
        user_message = self._post_user_message(thread)

        self._patch_adapter(StubAdapter([{"content": "hello world"}]))

        self._run(agent, thread, user_message)

        assistant = self._messages(thread, "assistant")
        self.assertEqual(len(assistant), 1)
        self.assertEqual(assistant.body_json.get("content"), "hello world")

    def test_tool_call_loop(self):
        agent = self._create_agent(tool_ids=[(6, 0, [self.tool.id])])
        thread = self._create_thread(agent)
        user_message = self._post_user_message(thread)

        stub = StubAdapter(
            [
                {"tool_calls": [_tool_call("echo")]},
                {"content": "done"},
            ]
        )
        self._patch_adapter(stub)
        self._patch_executor(StubExecutor())

        self._run(agent, thread, user_message)

        self.assertEqual(len(stub.calls), 2)
        assistant = self._messages(thread, "assistant")
        self.assertEqual(len(assistant), 2)
        self.assertEqual(assistant[-1].body_json.get("content"), "done")

        tool_messages = self._messages(thread, "tool")
        self.assertEqual(len(tool_messages), 1)
        self.assertEqual(tool_messages.body_json["status"], "completed")
        self.assertEqual(tool_messages.body_json["result"], {"echoed": {"x": 1}})

    def test_tool_calls_max_reached(self):
        agent = self._create_agent(
            tool_ids=[(6, 0, [self.tool.id])], tool_calls_max=2,
        )
        thread = self._create_thread(agent)
        user_message = self._post_user_message(thread)

        stub = StubAdapter(
            [{"tool_calls": [_tool_call("echo")]}, {"tool_calls": [_tool_call("echo")]}]
        )
        self._patch_adapter(stub)
        self._patch_executor(StubExecutor())

        events = self._run(agent, thread, user_message)

        self.assertEqual(len(stub.calls), 2)
        self.assertEqual(len(self._messages(thread, "tool")), 2)
        self.assertTrue(any(e.get("type") == "limit_reached" for e in events))

    def test_tool_execution_error(self):
        agent = self._create_agent(tool_ids=[(6, 0, [self.tool.id])])
        thread = self._create_thread(agent)
        user_message = self._post_user_message(thread)

        stub = StubAdapter(
            [
                {"tool_calls": [_tool_call("echo")]},
                {"content": "recovered"},
            ]
        )
        self._patch_adapter(stub)

        class FailingExecutor(StubExecutor):
            def execute(self, tool, parameters, session=None):
                raise RuntimeError("boom")

        self._patch_executor(FailingExecutor())

        events = self._run(agent, thread, user_message)

        tool_messages = self._messages(thread, "tool")
        self.assertEqual(len(tool_messages), 1)
        self.assertEqual(tool_messages.body_json["status"], "error")
        self.assertEqual(tool_messages.body_json["error"], "boom")
        self.assertTrue(any(e.get("type") == "tool_failed" for e in events))

    def test_llm_error_posts_error_message(self):
        agent = self._create_agent()
        thread = self._create_thread(agent)
        user_message = self._post_user_message(thread)

        self._patch_adapter(StubAdapter([RuntimeError("api down")]))

        self._run(agent, thread, user_message)

        errors = self.env["mail.message"].search(
            [
                ("model", "=", "llm.thread"),
                ("res_id", "=", thread.id),
                ("is_error", "=", True),
            ]
        )
        self.assertEqual(len(errors), 1)
        self.assertIn("api down", errors.body)
