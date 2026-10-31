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

    def test_unassigned_tool_admin_only(self):
        group = self._make_group("MCP Visibility A")
        tool = self.env["llm.tool"].search([], limit=1)
        tool.allowed_group_ids = [(5,)]

        member = self._make_user("mcp_vis_member_a", group)
        admin = self.env.ref("base.user_admin")

        self.assertNotIn(tool.name, self._tool_names(member))
        self.assertIn(tool.name, self._tool_names(admin))

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

    def test_authorized_users_lists_group_members(self):
        group = self._make_group("MCP Auth Members")
        other = self._make_group("MCP Auth Others")
        tool = self.env["llm.tool"].search([], limit=1)
        tool.allowed_group_ids = [(6, 0, [group.id])]

        member = self._make_user("mcp_auth_member", group)
        outsider = self._make_user("mcp_auth_outsider", other)

        self.assertIn(member, tool.authorized_user_ids)
        self.assertNotIn(outsider, tool.authorized_user_ids)

    def test_unrestricted_tool_authorized_users_are_admins(self):
        tool = self.env["llm.tool"].search([], limit=1)
        tool.allowed_group_ids = [(5,)]
        admin = self.env.ref("base.user_admin")
        self.assertIn(admin, tool.authorized_user_ids)


@tagged("post_install", "-at_install")
class TestMCPToolExposeFlag(TransactionCase):
    """``expose_to_mcp`` gates which tools the MCP server re-publishes."""

    def _remote_tool(self, name="remote_probe", **kwargs):
        client = self.env["llm.mcp.client"].create(
            {"name": "probe", "url": "http://localhost:1/mcp"}
        )
        values = {
            "name": name,
            "executor": "mcp",
            "source": "remote",
            "mcp_client_id": client.id,
            "res_method": name,
            "description": "remote tool",
            "input_schema": '{"type": "object", "properties": {}}',
        }
        values.update(kwargs)
        return self.env["llm.tool"].create(values)

    def _tool_names(self, user):
        result = self.env["llm.tool"].with_user(user).get_mcp_tools_list()
        return {tool.name for tool in result.tools}

    def test_remote_tool_defaults_to_not_exposed(self):
        tool = self._remote_tool()
        self.assertFalse(tool.expose_to_mcp)

    def test_code_tool_defaults_to_exposed(self):
        tool = self.env["llm.tool"].search([("source", "=", "code")], limit=1)
        self.assertTrue(tool.expose_to_mcp)

    def test_remote_tool_hidden_from_mcp_list_by_default(self):
        tool = self._remote_tool(name="hidden_remote")
        admin = self.env.ref("base.user_admin")
        self.assertNotIn(tool.name, self._tool_names(admin))

    def test_remote_tool_exposed_after_opt_in(self):
        tool = self._remote_tool(name="opted_in_remote")
        tool.expose_to_mcp = True
        admin = self.env.ref("base.user_admin")
        self.assertIn(tool.name, self._tool_names(admin))

    def test_remote_tool_not_callable_when_not_exposed(self):
        tool = self._remote_tool(name="uncallable_remote")
        admin = self.env.ref("base.user_admin")
        with self.assertRaises(exceptions.UserError):
            self.env["llm.tool"].with_user(admin).execute_mcp_tool(
                {"name": tool.name, "arguments": {}}
            )
