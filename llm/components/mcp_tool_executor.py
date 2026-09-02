"""``mcp`` executor: forward the call to a remote MCP server."""

from odoo import _
from odoo.exceptions import UserError, ValidationError

from odoo.addons.component.core import Component


class McpToolExecutor(Component):
    _name = "mcp.tool.executor"
    _inherit = "llm.tool.executor"
    _usage = "mcp"

    def execute(self, params):
        tool = self.collection
        tool.ensure_one()
        if not tool.mcp_client_id:
            raise UserError(
                _("Tool '%(name)s' has no MCP service configured.", name=tool.name)
            )
        return tool.mcp_client_id.call_tool(tool.res_method or tool.name, params)

    def validate(self, tool):
        if not tool.mcp_client_id:
            raise ValidationError(
                _(
                    "Tool '%(name)s' uses the MCP executor, which needs an "
                    "MCP service.",
                    name=tool.name,
                )
            )
