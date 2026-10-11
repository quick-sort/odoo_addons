"""Built-in tool for retrieving a module's orchestration guide."""

from typing import Any, Union

from odoo import models

from ..decorators import llm_tool


class LLMToolBuiltinGuide(models.AbstractModel):
    _name = "llm.tool.builtin.guide"
    _description = "Built-in tool for retrieving module orchestration guides"

    @llm_tool(read_only_hint=True, destructive_hint=False)
    def odoo_model_guide_retriever(
        self,
        code: Union[str, None] = None,
    ) -> dict[str, Any]:
        """Return an addon module's orchestration guide.

        A guide tells an agent how to operate a module — which models to use,
        which methods to call and in what order, and what invariants to respect —
        without inferring it from raw schemas.

        Call with no ``code`` to list every guide visible to the current user
        (index: code, title, summary). Pass a ``code`` (usually the module name,
        e.g. "skillhub") to fetch one guide's full body.

        Only guides whose ``allowed_group_ids`` include the current user are
        returned; a user never sees a guide for a module they cannot use.
        """
        Guide = self.env["llm.tool.guide"]
        guides = Guide._readable_guides()

        if not code:
            return {
                "guides": [
                    {
                        "code": guide.code,
                        "title": guide.title,
                        "summary": guide.summary or "",
                    }
                    for guide in guides
                ]
            }

        guide = guides.filtered(lambda g: g.code == code)
        if not guide:
            return {"error": f"No accessible guide for '{code}'"}

        return {
            "code": guide.code,
            "title": guide.title,
            "summary": guide.summary or "",
            "body": guide.body or "",
        }

    def _mcp_dynamic_description(self):
        """Suffix appended to this tool's MCP description at list time.

        Lists the keywords of the guides the current user can read, so the agent
        can discover which modules have a guide without a round-trip. Computed
        per user, so a user who cannot see a module's guide never sees its
        keyword either.
        """
        guides = self.env["llm.tool.guide"]._readable_guides()
        keywords = [guide.keyword for guide in guides if guide.keyword]
        if not keywords:
            return ""
        return "Available module guides: " + ", ".join(keywords) + "."
