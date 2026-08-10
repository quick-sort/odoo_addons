# Copyright 2026 Rui
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

"""Splitter backend model.

Polymorphic host for chunking implementations: ``splitter_type`` maps to a
component ``usage`` in the ``knowledge.splitter`` collection. Sizing is
configured on the splitter record (``chunk_size``, ``chunk_overlap``).
"""

from odoo import api, fields, models


class KnowledgeSplitter(models.Model):
    _name = "knowledge.splitter"
    _description = "Knowledge Splitter"
    _inherit = ["collection.base"]
    _backend_name = "knowledge_splitter"

    name = fields.Char(required=True)
    splitter_type = fields.Selection(
        selection=lambda self: self._selection_splitter_type(),
        required=True,
    )
    active = fields.Boolean(default=True)
    chunk_size = fields.Integer(
        default=500,
        help="Target size of each chunk (in characters or tokens, depending "
        "on the splitter type).",
    )
    chunk_overlap = fields.Integer(
        default=50,
        help="Number of characters/tokens shared between consecutive chunks.",
    )

    @api.model
    def _selection_splitter_type(self):
        return [
            (usage, usage.replace("_", " ").title())
            for usage in self._get_available_splitters()
        ]

    @api.model
    def _get_available_splitters(self):
        """Usages of the splitters shipped with this addon."""
        return ["recursive", "token"]

    def _get_adapter(self):
        self.ensure_one()
        if not self.splitter_type:
            return None
        with self.work_on(self._name) as work:
            return work.component(usage=self.splitter_type)
