"""Built-in tool for retrieving a module's orchestration guide."""

from typing import Any, Union

from odoo import models

from ..decorators import llm_tool


class LLMToolBuiltinGuide(models.AbstractModel):
    _name = "llm.tool.builtin.guide"
    _description = "Built-in tool for retrieving module orchestration guides"

    @llm_tool(
        read_only_hint=True,
        destructive_hint=False,
        groups=("llm.group_llm_user",),
    )
    def odoo_model_guide_retriever(
        self,
        code: Union[str, None] = None,
        query: Union[str, None] = None,
    ) -> dict[str, Any]:
        """Return an addon module's orchestration guide.

        A guide tells an agent how to operate a module — which models to use,
        which methods to call and in what order, and what invariants to respect —
        without inferring it from raw schemas.

        Three modes:

        - Pass a ``code`` (usually the module name, e.g. "skillhub") to fetch one
          guide's full body.
        - Pass a ``query`` to search the visible guides by a case-insensitive
          substring over code/title/keyword/summary and get the matching index
          (code, title, summary). Use it to narrow a large collection before
          fetching bodies.
        - Pass neither to get a compact overview grouped by code prefix — one
          line per group (``code`` + ``guide_count``), so a large collection
          stays cheap to list. Drill into a group with ``query``.

        Only guides whose ``allowed_group_ids`` include the current user are
        returned; a user never sees a guide for a module they cannot use.
        """
        Guide = self.env["llm.tool.guide"]
        guides = Guide._readable_guides()

        if code:
            guide = guides.filtered(lambda g: g.code == code)
            if not guide:
                return {"error": f"No accessible guide for '{code}'"}
            return {
                "code": guide.code,
                "title": guide.title,
                "summary": guide.summary or "",
                "body": guide.body or "",
            }

        q = (query or "").strip().lower()
        if q:
            matches = guides.filtered(
                lambda g: q in " ".join(
                    [g.code or "", g.title or "", g.keyword or "", g.summary or ""]
                ).lower()
            )
            return {
                "guides": [
                    {"code": g.code, "title": g.title, "summary": g.summary or ""}
                    for g in matches
                ],
                "count": len(matches),
            }

        groups: dict[str, int] = {}
        for g in guides:
            key = g.code.split("-", 1)[0]
            groups[key] = groups.get(key, 0) + 1
        return {
            "groups": [
                {"code": key, "guide_count": count}
                for key, count in sorted(groups.items())
            ],
            "hint": (
                'Pass query="<group code>" to list a group\'s guides, or '
                'code="<full code>" to read one guide.'
            ),
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
