import logging
import time

from mcp.types import CallToolResult, ListToolsResult, TextContent, Tool

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)

RESULT_SUMMARY_MAX = 2000


class LLMTool(models.Model):
    _inherit = "llm.tool"

    allowed_group_ids = fields.Many2many(
        "res.groups",
        string="Allowed Groups",
        help="Only users in one of these groups see and call this tool via MCP. "
        "Leave empty to expose it to everyone.",
    )

    authorized_user_ids = fields.Many2many(
        "res.users",
        string="Authorized Users",
        compute="_compute_authorized_user_ids",
        help="Users who can currently see and call this tool via MCP: the "
        "members of its allowed groups. With no allowed group the tool is "
        "open to everyone, and system administrators are never restricted.",
    )

    @api.depends("allowed_group_ids")
    def _compute_authorized_user_ids(self):
        for tool in self:
            if tool.allowed_group_ids:
                tool.authorized_user_ids = tool.allowed_group_ids.users.filtered(
                    "active"
                )
            else:
                tool.authorized_user_ids = False

    def _mcp_visibility_domain(self):
        """Domain fragment restricting tools to the authenticated user.

        A tool with no ``allowed_group_ids`` is visible to everyone; otherwise
        it is visible only to users sharing at least one of those groups.
        Superusers see everything.
        """
        if self.env.su or self.env.user.has_group("base.group_system"):
            return []
        return [
            "|",
            ("allowed_group_ids", "=", False),
            ("allowed_group_ids", "in", self.env.user.group_ids.ids),
        ]

    @api.model
    def get_mcp_tools_list(self, params=None):
        """Handle MCP tools/list request - return MCP ListToolsResult"""
        import ast
        config = self.env["llm.mcp.server.config"].get_active_config()
        domain = ast.literal_eval(config.tool_domain or "[('active', '=', True)]")
        domain += self._mcp_visibility_domain()
        active_tools = self.sudo().search(domain)
        mcp_tools = []

        for tool in active_tools:
            # Get tool definition as dict
            tool_definition = tool.get_tool_definition()
            # Convert to MCP Tool object
            mcp_tool = Tool(**tool_definition)
            mcp_tools.append(mcp_tool)

        return ListToolsResult(tools=mcp_tools)

    @api.model
    def execute_mcp_tool(self, params=None):
        """Handle MCP tools/call request - return MCP CallToolResult"""
        if not params:
            raise UserError(_("Missing parameters for tool call"))

        tool_name = params.get("name")
        if not tool_name:
            raise UserError(_("Missing tool name in parameters"))

        tool_arguments = params.get("arguments", {})

        # Find the tool by name, restricted to what the user is allowed to see.
        tool = self.search(
            [("name", "=", tool_name), ("active", "=", True)]
            + self._mcp_visibility_domain(),
            limit=1,
        )
        if not tool:
            raise UserError(_("Tool '%s' not found or inactive") % tool_name)

        start = time.monotonic()
        try:
            # Execute the tool
            result = tool.execute(tool_arguments)

            # Return MCP CallToolResult
            content = [
                TextContent(type="text", text=str(result) if result is not None else "")
            ]
            result = CallToolResult(content=content, is_error=False)
        except Exception as e:
            _logger.exception(f"Error executing tool {tool_name}")
            # Return error result
            error_content = [
                TextContent(type="text", text=f"Tool execution failed: {str(e)}")
            ]
            result = CallToolResult(content=error_content, is_error=True)

        try:
            self._mcp_audit_tool_call(params, result, time.monotonic() - start)
        except Exception:
            # A failed audit write must never break the tool response.
            _logger.exception("Failed to record MCP tool call audit row")

        return result

    @api.model
    def _mcp_audit_tool_call(self, params, result, duration):
        summary = ""
        content = getattr(result, "content", None) or []
        if content:
            summary = getattr(content[0], "text", "") or ""
        tool_name = params.get("name") or ""

        self.env["llm.mcp.tool.call"].create(
            {
                "user_id": self.env.uid,
                "tool_id": self.search([("name", "=", tool_name)], limit=1).id or False,
                "tool_name": tool_name,
                "session_id": self._mcp_session_id_from_request(),
                "arguments": params.get("arguments") or {},
                "is_error": bool(getattr(result, "is_error", False)),
                "result_summary": summary[:RESULT_SUMMARY_MAX],
                "duration_ms": int(duration * 1000),
            }
        )

    @staticmethod
    def _mcp_session_id_from_request():
        # execute_mcp_tool is also called from tests and shell code where
        # no HTTP request exists.
        try:
            from odoo.http import request

            return request.httprequest.headers.get("mcp-session-id") or ""
        except RuntimeError:
            return ""
