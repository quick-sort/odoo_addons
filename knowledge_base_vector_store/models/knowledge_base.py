# Copyright 2026 Rui
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

"""Extend knowledge.base with chunking/vectorization wiring."""

from odoo import api, fields, models


class KnowledgeBase(models.Model):
    _inherit = "knowledge.base"

    state = fields.Selection(
        selection_add=[
            ("chunked", "Chunked"),
            ("vectorized", "Vectorized"),
        ]
    )
    chunkset_ids = fields.One2many(
        comodel_name="knowledge.chunkset",
        inverse_name="kb_id",
        string="Chunking Configurations",
    )
    chunkset_count = fields.Integer(compute="_compute_chunkset_count")

    @api.depends("chunkset_ids")
    def _compute_chunkset_count(self):
        for kb in self:
            kb.chunkset_count = len(kb.chunkset_ids)

    def _refresh_state(self):
        super()._refresh_state()
        for kb in self:
            if "error" in kb.source_ids.mapped("state"):
                continue
            chunkset_states = set(kb.chunkset_ids.mapped("state"))
            vectors = self.env["knowledge.vector"].search(
                [("chunkset_id", "in", kb.chunkset_ids.ids)]
            )
            if "vectorized" in vectors.mapped("state"):
                kb.state = "vectorized"
            elif chunkset_states and chunkset_states <= {"chunked"}:
                kb.state = "chunked"
