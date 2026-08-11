# Copyright 2026 Rui
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

"""Register the qdrant store usage on the backend model."""

from odoo import models


class KnowledgeVectorStore(models.Model):
    _inherit = "knowledge.vector.store"

    def _get_available_vector_stores(self):
        return super()._get_available_vector_stores() + ["qdrant"]
