from odoo.tests import tagged
from odoo.tests.common import TransactionCase

from odoo.addons.llm_mcp_server.controllers.mcp_controller import _mcp_result_payload


@tagged("post_install", "-at_install")
class TestMCPWireFormat(TransactionCase):
    """Lock the MCP wire format to camelCase.

    Strict SDK clients (the official TypeScript SDK inside mcp-remote and
    Claude Code) validate payloads with zod and reject snake_case keys.
    """

    def test_initialize_payload_is_camelcase(self):
        config = self.env["llm.mcp.server.config"].search([], limit=1)
        result = config.handle_initialize_request(
            protocol_version="2025-06-18"
        )
        payload = _mcp_result_payload(result)
        self.assertIn("protocolVersion", payload)
        self.assertIn("serverInfo", payload)
        self.assertNotIn("protocol_version", payload)

    def test_tools_list_payload_is_camelcase(self):
        result = self.env["llm.tool"].get_mcp_tools_list()
        payload = _mcp_result_payload(result)
        tools = payload["tools"]
        self.assertTrue(tools)
        self.assertIn("inputSchema", tools[0])
        self.assertNotIn("input_schema", tools[0])
        annotations = tools[0].get("annotations") or {}
        self.assertIn("readOnlyHint", annotations)
        self.assertNotIn("read_only_hint", annotations)

    def test_client_config_adds_allow_http_for_plain_http(self):
        config = self.env["llm.mcp.server.config"].search([], limit=1)
        config.external_url = "http://174.15.0.58:8080"
        configs = config.generate_client_configs()
        self.assertIn('"--allow-http"', configs["claude_desktop"])

    def test_client_config_omits_allow_http_for_https(self):
        config = self.env["llm.mcp.server.config"].search([], limit=1)
        config.external_url = "https://example.com"
        configs = config.generate_client_configs()
        self.assertNotIn("--allow-http", configs["claude_code"])
