# Copyright 2026 Rui
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

"""The knowledge base itself: a logical container (no polymorphism of its own)
holding a hierarchy of KBs and a flat list of sources. Polymorphism lives in
the extractor/splitter/vector-store backend models it references.
"""

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class KnowledgeBase(models.Model):
    _name = "knowledge.base"
    _description = "Knowledge Base"
    _inherit = ["mail.thread"]
    _order = "sequence, complete_name"
    _parent_name = "parent_id"
    _parent_store = True

    name = fields.Char(required=True, tracking=True)
    active = fields.Boolean(default=True)
    sequence = fields.Integer(
        default=10,
        help="Order of this knowledge base among its siblings.",
    )
    parent_id = fields.Many2one(
        comodel_name="knowledge.base",
        string="Parent Knowledge Base",
        ondelete="cascade",
        index=True,
    )
    child_ids = fields.One2many(
        comodel_name="knowledge.base",
        inverse_name="parent_id",
        string="Sub Knowledge Bases",
    )
    parent_path = fields.Char(index=True)
    complete_name = fields.Char(
        compute="_compute_complete_name",
        store=True,
        recursive=True,
    )
    md_backend_id = fields.Many2one(
        comodel_name="storage.backend",
        string="Extraction Backend",
        required=True,
        tracking=True,
        help="Storage backend where extracted markdown and chunks are stored.",
    )
    extractor_id = fields.Many2one(
        comodel_name="knowledge.extractor",
        string="Default Extractor",
        ondelete="restrict",
        tracking=True,
    )
    source_ids = fields.One2many(
        comodel_name="knowledge.source",
        inverse_name="kb_id",
        string="Sources",
    )
    source_count = fields.Integer(
        compute="_compute_source_count",
    )
    state = fields.Selection(
        selection=[
            ("scope", "Defining Scope"),
            ("extracting", "Extracting"),
            ("extracted", "Extracted"),
            ("error", "Error"),
        ],
        default="scope",
        tracking=True,
    )

    @api.depends("source_ids")
    def _compute_source_count(self):
        for kb in self:
            kb.source_count = len(kb.source_ids)

    @api.depends("name", "parent_id.complete_name")
    def _compute_complete_name(self):
        for kb in self:
            kb.complete_name = (
                kb.parent_id.complete_name + " / " + kb.name
                if kb.parent_id
                else kb.name
            )

    @api.constrains("parent_id")
    def _check_parent_recursion(self):
        if not self._check_recursion(parent="parent_id"):
            raise ValidationError(
                _("Knowledge base hierarchy must not contain cycles.")
            )

    # ------------------------------------------------------------------
    # Extraction workflow
    # ------------------------------------------------------------------
    def action_extract_all(self):
        """Enqueue one extraction job per source (async)."""
        for kb in self:
            if not kb.source_ids:
                raise ValidationError(
                    _(
                        "Add at least one source to knowledge base '%s' "
                        "before extracting.",
                        kb.name,
                    )
                )
        self.write({"state": "extracting"})
        for kb in self:
            for source in kb.source_ids:
                source.with_delay(
                    channel="root.knowledge",
                    description=_("Extract %s") % source.display_name,
                )._extract()
        return True

    def _extract_all(self):
        """Synchronous extraction, used by tests and scripts."""
        self.write({"state": "extracting"})
        for kb in self:
            for source in kb.source_ids:
                source._extract()
            kb._refresh_state()

    def _refresh_state(self):
        """Recompute the coarse state from the sources' states."""
        for kb in self:
            states = set(kb.source_ids.mapped("state"))
            if "error" in states:
                kb.state = "error"
            elif states and states <= {"extracted"}:
                kb.state = "extracted"
