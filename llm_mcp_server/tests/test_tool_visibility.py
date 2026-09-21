from odoo import exceptions
from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestMCPToolVisibility(TransactionCase):

    def _make_group(self, name):
        return self.env["res.groups"].create({"name": name})

    def _make_user(self, login, group):
        return self.env["res.users"].create(
            {
                "name": login,
                "login": login,
                "group_ids": [
                    (4, self.env.ref("base.group_user").id),
                    (4, group.id),
                ],
            }
        )

    def _tool_names(self, user):
        result = self.env["llm.tool"].with_user(user).get_mcp_tools_list()
        return {tool.name for tool in result.tools}

    def test_unassigned_tool_visible_to_everyone(self):
        group = self._make_group("MCP Visibility A")
        other = self._make_group("MCP Visibility B")
        tool = self.env["llm.tool"].search([], limit=1)
        tool.allowed_group_ids = [(5,)]

        member = self._make_user("mcp_vis_member_a", group)
        outsider = self._make_user("mcp_vis_outsider_a", other)

        self.assertIn(tool.name, self._tool_names(member))
        self.assertIn(tool.name, self._tool_names(outsider))

    def test_group_restricted_tool_hidden_from_outsider(self):
        group = self._make_group("MCP Visibility C")
        other = self._make_group("MCP Visibility D")
        tool = self.env["llm.tool"].search([], limit=1)
        tool.allowed_group_ids = [(6, 0, [group.id])]

        member = self._make_user("mcp_vis_member_c", group)
        outsider = self._make_user("mcp_vis_outsider_c", other)

        self.assertIn(tool.name, self._tool_names(member))
        self.assertNotIn(tool.name, self._tool_names(outsider))

    def test_group_restricted_tool_cannot_be_called_by_outsider(self):
        group = self._make_group("MCP Visibility E")
        other = self._make_group("MCP Visibility F")
        tool = self.env["llm.tool"].search(
            [("name", "=", "odoo_record_retriever")], limit=1
        )
        tool.allowed_group_ids = [(6, 0, [group.id])]

        outsider = self._make_user("mcp_vis_outsider_e", other)
        with self.assertRaises(exceptions.UserError):
            self.env["llm.tool"].with_user(outsider).execute_mcp_tool(
                {"name": tool.name, "arguments": {"model": "res.partner", "limit": 1}}
            )
