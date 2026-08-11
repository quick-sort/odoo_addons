# Copyright 2026 Rui
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

"""Register the trafilatura extractor usage on the backend model."""

from odoo import models


class KnowledgeExtractor(models.Model):
    _inherit = "knowledge.extractor"

    def _get_available_extractors(self):
        return super()._get_available_extractors() + ["trafilatura"]
