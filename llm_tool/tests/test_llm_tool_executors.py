"""Tests for the three executors and the dispatch that picks one."""

import json
from unittest.mock import patch

from odoo.exceptions import UserError
from odoo.tests import tagged

from .common import BUILTIN_MODEL, LLMToolCase


@tagged("post_install", "-at_install")
class TestModelMethodExecutor(LLMToolCase):
    def test_calls_the_method_on_the_model(self):
        result = self._builtin().execute(
            {"model": "res.users", "fields": ["login"], "limit": 1}
        )

        self.assertEqual(len(result), 1)
        self.assertIn("login", result[0])

    def test_coerces_arguments_before_the_call(self):
        """LLMs send numbers as strings; pydantic coerces them."""
        result = self._builtin().execute(
            {"model": "res.users", "fields": ["login"], "limit": "1"}
        )

        self.assertEqual(len(result), 1)

    def test_omitted_optional_keeps_the_python_default(self):
        """Only supplied keys are forwarded, so defaults stay the method's."""
        result = self._builtin().execute({"model": "res.users"})

        self.assertGreater(len(result[0]), 1, "no 'fields' means read everything")

    def test_res_id_binds_the_call_to_one_record(self):
        """A tool may be registered against a specific record."""
        partner = self.env["res.partner"].create({"name": "Bound Probe"})
        tool = self._manual_tool(
            name="bound_read",
            res_model="res.partner",
            res_method="read",
            res_id=partner.id,
            input_schema='{"type": "object", "properties": '
            '{"fields": {"type": "array", "items": {"type": "string"}}}}',
        )

        result = tool.execute({"fields": ["name"]})

        self.assertEqual(result[0]["name"], "Bound Probe")

    def test_deleted_bound_record_is_reported(self):
        partner = self.env["res.partner"].create({"name": "Doomed"})
        tool = self._manual_tool(
            name="dangling_bound",
            res_model="res.partner",
            res_method="read",
            res_id=partner.id,
            input_schema='{"type": "object", "properties": {}}',
        )
        partner.unlink()

        with self.assertRaises(UserError) as ctx:
            tool.execute({})

        self.assertIn("no longer exists", str(ctx.exception))

    def test_resolved_callable_is_bound(self):
        """Unbound would leak ``self`` into the derived schema."""
        tool = self._builtin()
        method = tool._dispatch("resolve_callable", tool)

        self.assertTrue(hasattr(method, "__self__"))


@tagged("post_install", "-at_install")
class TestServerActionExecutor(LLMToolCase):
    def _action(self, code):
        return self.env["ir.actions.server"].create(
            {
                "name": "probe action",
                "model_id": self.env.ref("base.model_res_partner").id,
                "state": "code",
                "code": code,
            }
        )

    def test_arguments_arrive_in_the_context(self):
        """run() takes no arguments, so they travel via llm_tool_params."""
        action = self._action(
            "action = {'seen': env.context.get('llm_tool_params')}"
        )
        tool = self._manual_tool(
            name="sa_echo",
            executor="server_action",
            server_action_id=action.id,
            res_model=False,
            res_method=False,
            input_schema='{"type": "object", "properties": '
            '{"greeting": {"type": "string"}}}',
        )

        result = tool.execute({"greeting": "hello"})

        self.assertEqual(result, {"seen": {"greeting": "hello"}})

    def test_schema_still_filters_arguments(self):
        """Undeclared keys are dropped before the action ever sees them."""
        action = self._action(
            "action = {'seen': env.context.get('llm_tool_params')}"
        )
        tool = self._manual_tool(
            name="sa_filtered",
            executor="server_action",
            server_action_id=action.id,
            res_model=False,
            res_method=False,
            input_schema='{"type": "object", "properties": '
            '{"kept": {"type": "string"}}}',
        )

        result = tool.execute({"kept": "yes", "dropped": "no"})

        self.assertEqual(result["seen"], {"kept": "yes"})

    def test_missing_action_is_reported(self):
        tool = self._manual_tool(
            name="sa_missing",
            executor="server_action",
            server_action_id=self._action("action = None").id,
            res_model=False,
            res_method=False,
            input_schema='{"type": "object", "properties": {}}',
        )
        # Bypass _check_executor_configuration, which rightly refuses this via
        # the ORM: simulate the action having been deleted underneath the row.
        self.env.cr.execute(
            "UPDATE llm_tool SET server_action_id = NULL WHERE id = %s", [tool.id]
        )
        tool.invalidate_recordset(["server_action_id"])

        with self.assertRaises(UserError) as ctx:
            tool.execute({})

        self.assertIn("server action", str(ctx.exception).lower())


@tagged("post_install", "-at_install")
class TestDispatch(LLMToolCase):
    def test_unknown_executor_reports_a_missing_addon(self):
        tool = self._manual_tool(name="ghost_executor")
        # Bypass the selection to simulate an uninstalled addon.
        self.env.cr.execute(
            "UPDATE llm_tool SET executor = 'gone' WHERE id = %s", [tool.id]
        )
        tool.invalidate_recordset(["executor"])

        with self.assertRaises(UserError) as ctx:
            tool.execute({"model": "res.users"})

        self.assertIn("gone", str(ctx.exception))

    def test_narrowing_is_enforced_not_advisory(self):
        """The stored schema is what execute() validates against."""
        tool = self._manual_tool(
            name="narrowed_exec",
            input_schema='{"type": "object", "properties": '
            '{"model": {"type": "string"}}, "required": ["model"]}',
        )

        result = tool.execute({"model": "res.users", "fields": ["login"], "limit": 1})

        # 'fields' and 'limit' were dropped, so we got full records, not one
        # field, and the method's own limit=100 applied.
        self.assertGreater(len(result[0]), 1)

    def test_tool_definition_is_mcp_shaped(self):
        definition = self._builtin().get_tool_definition()

        self.assertEqual(definition["name"], "odoo_record_retriever")
        self.assertIn("inputSchema", definition)
        self.assertIn("readOnlyHint", definition["annotations"])
        self.assertTrue(definition["description"])

    def test_annotations_are_always_emitted(self):
        """fields.Boolean is never None, so all four hints are always present."""
        annotations = self._builtin().get_tool_definition()["annotations"]

        self.assertEqual(
            set(annotations),
            {"readOnlyHint", "idempotentHint", "destructiveHint", "openWorldHint"},
        )

    def test_definition_falls_back_to_the_docstring(self):
        """For a code row created since the last scan."""
        tool = self.LLMTool.create(
            {
                "name": "fresh_code_row",
                "source": "code",
                "executor": "model_method",
                "res_model": BUILTIN_MODEL,
                "res_method": "odoo_record_retriever",
            }
        )

        definition = tool.get_tool_definition()

        self.assertIn("Retrieve records", definition["description"])
        self.assertIn("model", json.loads(json.dumps(definition["inputSchema"]))["properties"])



@tagged("post_install", "-at_install")
class TestMcpExecutor(LLMToolCase):
    """``mcp`` is a first-class executor now, not a value added by another addon.

    ``llm.mcp.client`` used to live in a separate addon (``llm_tool_mcp``); it is
    now part of ``llm_tool`` itself, so a tool can point at a model method, a
    server action, or a remote MCP tool without installing anything extra.
    """

    def _client(self, **kwargs):
        values = {"name": "probe client", "url": "http://localhost:1/mcp"}
        values.update(kwargs)
        return self.env["llm.mcp.client"].create(values)

    def test_mcp_needs_a_client(self):
        with self.assertRaises(Exception):
            self._manual_tool(
                name="orphan_mcp",
                executor="mcp",
                res_model=False,
                res_method="search",
            )

    def test_execute_forwards_to_the_client(self):
        client = self._client()
        tool = self._manual_tool(
            name="remote_search",
            executor="mcp",
            source="remote",
            mcp_client_id=client.id,
            res_model=False,
            res_method="search",
            input_schema='{"type": "object", "properties": '
            '{"query": {"type": "string"}}}',
        )

        with patch.object(
            type(client), "call_tool", lambda self, name, args: {"name": name, "args": args}
        ):
            result = tool.execute({"query": "hello"})

        self.assertEqual(result, {"name": "search", "args": {"query": "hello"}})

    def test_falls_back_to_the_tool_name_when_res_method_is_empty(self):
        client = self._client()
        tool = self._manual_tool(
            name="bare_name_tool",
            executor="mcp",
            source="remote",
            mcp_client_id=client.id,
            res_model=False,
            res_method=False,
            input_schema='{"type": "object", "properties": {}}',
        )

        with patch.object(
            type(client), "call_tool", lambda self, name, args: {"name": name}
        ):
            result = tool.execute({})

        self.assertEqual(result["name"], "bare_name_tool")

    def test_mcp_rows_are_untouched_by_the_code_scan(self):
        """source='remote' keeps them out of _sync_tools_to_db entirely."""
        client = self._client()
        tool = self._manual_tool(
            name="remote_untouched",
            executor="mcp",
            source="remote",
            mcp_client_id=client.id,
            res_model=False,
            res_method="probe",
        )

        self.LLMTool._sync_tools_to_db()
        tool.invalidate_recordset(["active", "description"])

        self.assertTrue(tool.active)
        self.assertEqual(tool.description, "Test tool description")


@tagged("post_install", "-at_install")
class TestMcpClientSync(LLMToolCase):
    """``action_sync_tools`` imports a remote tool list into the registry."""

    def _client(self):
        return self.env["llm.mcp.client"].create(
            {"name": "sync probe", "url": "http://localhost:1/mcp"}
        )

    def test_sync_creates_remote_rows(self):
        client = self._client()
        remote = [
            {"name": "web_search", "description": "Search the web", "inputSchema": {"type": "object"}},
        ]

        with patch.object(type(client), "list_tools", lambda self: remote):
            client.action_sync_tools()

        tool = self.LLMTool.search([("name", "=", "web_search")])
        self.assertTrue(tool)
        self.assertEqual(tool.executor, "mcp")
        self.assertEqual(tool.source, "remote")
        self.assertEqual(tool.mcp_client_id, client)
        self.assertEqual(tool.res_method, "web_search")

    def test_sync_updates_an_existing_row_by_res_method(self):
        client = self._client()
        with patch.object(
            type(client), "list_tools",
            lambda self: [{"name": "t1", "description": "v1", "inputSchema": {}}],
        ):
            client.action_sync_tools()
        tool = self.LLMTool.search([("mcp_client_id", "=", client.id), ("res_method", "=", "t1")])

        with patch.object(
            type(client), "list_tools",
            lambda self: [{"name": "t1", "description": "v2", "inputSchema": {}}],
        ):
            client.action_sync_tools()
        tool.invalidate_recordset(["description"])

        self.assertEqual(tool.description, "v2")
        self.assertEqual(
            self.LLMTool.search_count(
                [("mcp_client_id", "=", client.id), ("res_method", "=", "t1")]
            ),
            1,
            "must update in place, not duplicate",
        )

    def test_sync_archives_tools_removed_from_the_remote(self):
        client = self._client()
        with patch.object(
            type(client), "list_tools",
            lambda self: [{"name": "gone_soon", "description": "d", "inputSchema": {}}],
        ):
            client.action_sync_tools()
        tool = self.LLMTool.search([("mcp_client_id", "=", client.id), ("res_method", "=", "gone_soon")])

        with patch.object(type(client), "list_tools", lambda self: []):
            client.action_sync_tools()
        tool.invalidate_recordset(["active"])

        self.assertFalse(tool.active)
