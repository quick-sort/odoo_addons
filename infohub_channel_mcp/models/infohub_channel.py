from odoo import fields, models


class InfohubChannel(models.Model):
    _inherit = "infohub.channel"

    channel_type = fields.Selection(
        selection_add=[("mcp", "MCP / API")],
        ondelete={"mcp": "cascade"},
    )

    #: The MCP server to call. Its endpoint URL and API key live on the client
    #: record itself (LLM > Configuration > MCP Clients), so credentials are
    #: never duplicated onto the channel.
    mcp_client_id = fields.Many2one(
        "llm.mcp.client",
        string="MCP Client",
        help="MCP server this channel pulls news from.",
    )
    mcp_tool_name = fields.Char(
        string="Tool Name",
        help="Name of the tool to call on that server.",
    )
