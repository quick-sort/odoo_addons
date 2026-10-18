"""Tests for the guide retriever's dynamic MCP description."""

from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestGuideDynamicDescription(TransactionCase):
    def _guide_tool(self):
        result = self.env["llm.tool"].get_mcp_tools_list()
        return next(t for t in result.tools if t.name == "odoo_model_guide_retriever")

    def test_guide_keyword_appended_to_tool_description(self):
        self.env["llm.tool.guide"].create(
            {
                "code": "test-keyword",
                "title": "Test Keyword",
                "keyword": "test-keyword",
                "body": "How to operate the test keyword.",
            }
        )

        tool = self._guide_tool()

        self.assertIn("test-keyword", tool.description)

    def test_no_guides_yields_clean_description(self):
        self.env["llm.tool.guide"].search([]).unlink()

        tool = self._guide_tool()

        # Static docstring present, no dynamic suffix appended.
        self.assertIn("orchestration guide", tool.description)
        self.assertNotIn("Available module guides", tool.description)
