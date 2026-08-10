# Copyright 2026 Rui
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

"""Extend knowledge.source with chunking entry points."""

from odoo import models


class KnowledgeSource(models.Model):
    _inherit = "knowledge.source"

    def _chunk(self, chunkset_id):
        """Chunk this source into the given chunkset. Queue job body."""
        self.ensure_one()
        chunkset = self.env["knowledge.chunkset"].browse(chunkset_id)
        chunkset._chunk_source(self)
