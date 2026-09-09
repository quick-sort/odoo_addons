import logging

from odoo import _, api, fields, models
from odoo.exceptions import AccessError

_logger = logging.getLogger(__name__)


class LLMMCPToolCall(models.Model):
    _name = "llm.mcp.tool.call"
    _description = "MCP Tool Call Audit"
    _order = "create_date desc"

    user_id = fields.Many2one(
        "res.users",
        required=True,
        index=True,
        ondelete="restrict",
    )
    tool_id = fields.Many2one(
        "llm.tool",
        index=True,
        ondelete="set null",
    )
    tool_name = fields.Char(help="Name as called; kept when the tool row is gone")
    session_id = fields.Char(help="Mcp-Session-Id header, stateful mode only")
    arguments = fields.Json()
    is_error = fields.Boolean()
    result_summary = fields.Text(help="Truncated tool output or error text")
    duration_ms = fields.Integer()

    @api.ondelete(at_uninstall=False)
    def _only_manager_unlinks(self):
        if not self.env.user.has_group("llm.group_llm_manager"):
            raise AccessError(_("Only LLM Managers can delete MCP tool call logs."))
