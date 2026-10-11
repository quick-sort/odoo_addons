"""``llm.tool.guide`` — per-module orchestration guides for LLM agents.

A guide tells an agent *how to operate a module* — which models to touch, which
methods to call and in what order, and what invariants to respect — without the
agent having to infer it from raw schemas. Each addon contributes its own guide
via XML data; the ``odoo_model_guide_retriever`` built-in tool serves them.

See ``llm/docs/tool_exposure.md`` for the design.
"""

from odoo import fields, models


class LLMToolGuide(models.Model):
    _name = "llm.tool.guide"
    _description = "LLM Tool Orchestration Guide"
    _rec_name = "title"

    code = fields.Char(
        required=True,
        help="Stable slug, usually the module name (e.g. 'skillhub').",
    )
    title = fields.Char(required=True)
    summary = fields.Text(
        help="Header: a one-liner plus what operations this module exposes. "
        "Returned by the guide index."
    )
    body = fields.Text(
        help="Body: the full orchestration doc — per-operation sequence, "
        "invariants and gotchas. Returned on demand."
    )
    keyword = fields.Char(
        help="Short keyword folded into the retriever's MCP description so "
        "agents can discover the module without a round-trip. Keep it short."
    )
    allowed_group_ids = fields.Many2many(
        "res.groups",
        string="Allowed Groups",
        help="Only users in one of these groups see this guide through the "
        "retriever. Leave empty to expose it to everyone. Reference the same "
        "group(s) as the module's tools' allowed_group_ids.",
    )
    active = fields.Boolean(default=True)

    _unique_code = models.Constraint(
        "UNIQUE(code)",
        "A guide with this code already exists.",
    )

    def _visibility_domain(self):
        """Domain fragment restricting guides to the current user.

        Mirrors ``llm_mcp_server``'s ``_mcp_visibility_domain``: a guide with no
        ``allowed_group_ids`` is visible to everyone; otherwise only to users in
        one of those groups. Superusers see everything.
        """
        if self.env.su or self.env.user.has_group("base.group_system"):
            return []
        return [
            "|",
            ("allowed_group_ids", "=", False),
            ("allowed_group_ids", "in", self.env.user.group_ids.ids),
        ]

    def _readable_guides(self):
        """Guides visible to the current user, respecting ``allowed_group_ids``."""
        return self.search([("active", "=", True)] + self._visibility_domain())
