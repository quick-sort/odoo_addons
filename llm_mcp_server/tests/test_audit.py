from odoo import exceptions
from odoo.tests.common import TransactionCase
from odoo.tests import tagged


@tagged("post_install", "-at_install")
class TestMCPCallAudit(TransactionCase):

    def test_successful_call_is_audited(self):
        audit = self.env["llm.mcp.tool.call"]
        domain = [("tool_name", "=", "odoo_record_retriever")]
        before = audit.search_count(domain)

        result = self.env["llm.tool"].execute_mcp_tool(
            {
                "name": "odoo_record_retriever",
                "arguments": {"model": "res.partner", "limit": 1},
            }
        )
        self.assertFalse(result.is_error)

        rows = audit.search(domain)
        self.assertEqual(len(rows), before + 1)
        row = rows[0]
        self.assertEqual(row.user_id, self.env.user)
        tool = self.env["llm.tool"].search(
            [("name", "=", "odoo_record_retriever")], limit=1
        )
        self.assertEqual(row.tool_id, tool)
        self.assertFalse(row.is_error)
        self.assertEqual(row.arguments, {"model": "res.partner", "limit": 1})
        self.assertIn("display_name", row.result_summary)

    def test_failing_call_is_audited_as_error(self):
        audit = self.env["llm.mcp.tool.call"]
        domain = [("tool_name", "=", "odoo_record_retriever")]
        before = audit.search_count(domain)

        result = self.env["llm.tool"].execute_mcp_tool(
            {
                "name": "odoo_record_retriever",
                "arguments": {"model": "this.model.does.not.exist"},
            }
        )
        self.assertTrue(result.is_error)

        rows = audit.search(domain)
        self.assertEqual(len(rows), before + 1)
        self.assertTrue(rows[0].is_error)

    def test_unknown_tool_is_not_audited(self):
        audit = self.env["llm.mcp.tool.call"]
        before = audit.search_count([])

        with self.assertRaises(exceptions.UserError):
            self.env["llm.tool"].execute_mcp_tool(
                {"name": "no_such_tool", "arguments": {}}
            )

        self.assertEqual(audit.search_count([]), before)

    def test_audit_rows_readable_only_by_manager(self):
        self.env["llm.tool"].execute_mcp_tool(
            {
                "name": "odoo_record_retriever",
                "arguments": {"model": "res.partner", "limit": 1},
            }
        )
        row = self.env["llm.mcp.tool.call"].search([], limit=1)
        self.assertTrue(row)

        # Audit rows are created with the calling user's env; in this test
        # env the caller is the test user, who has no read access.
        user = self.env["res.users"].create(
            {"name": "MCP Audit Reader", "login": "mcp_audit_reader"}
        )
        with self.assertRaises(exceptions.AccessError):
            row.with_user(user).read(["tool_name"])

        manager = self.env.ref("llm.group_llm_manager")
        user.write({"group_ids": [(4, manager.id)]})
        self.assertEqual(row.with_user(user).tool_name, "odoo_record_retriever")
