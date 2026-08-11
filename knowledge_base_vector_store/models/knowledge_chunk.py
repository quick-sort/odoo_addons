# Copyright 2026 Rui
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

"""Lightweight chunk metadata. The chunk TEXT lives on the KB's md backend at
``<source_id>/chunks/<chunkset_id>/<sequence>.md``; this record only tracks
the mapping so the UI and vectorization can iterate chunks without parsing
the backend.
"""

from odoo import api, fields, models


class KnowledgeChunk(models.Model):
    _name = "knowledge.chunk"
    _description = "Knowledge Chunk"
    _order = "chunkset_id, source_id, sequence"

    chunkset_id = fields.Many2one(
        comodel_name="knowledge.chunkset",
        string="Chunking Configuration",
        required=True,
        ondelete="cascade",
        index=True,
    )
    source_id = fields.Many2one(
        comodel_name="knowledge.source",
        string="Source",
        required=True,
        ondelete="cascade",
        index=True,
    )
    sequence = fields.Integer()
    path = fields.Char(compute="_compute_path", store=True)
    file_size = fields.Integer()

    _chunkset_source_seq_uniq = models.Constraint(
        "UNIQUE (chunkset_id, source_id, sequence)",
        "A chunk sequence must be unique within a chunkset and source.",
    )

    @api.depends("chunkset_id", "source_id", "sequence")
    def _compute_path(self):
        for chunk in self:
            chunk.path = (
                "%s/chunks/%s/%s.md"
                % (chunk.source_id.id, chunk.chunkset_id.id, chunk.sequence)
                if chunk.chunkset_id and chunk.source_id
                else False
            )

    def _read_text(self):
        """Read this chunk's text from the KB md backend."""
        self.ensure_one()
        backend = self.chunkset_id.kb_id.md_backend_id
        return backend.get(self.path).decode("utf-8")
