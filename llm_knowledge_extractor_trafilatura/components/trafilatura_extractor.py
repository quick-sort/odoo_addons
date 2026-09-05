"""Trafilatura URL extractor."""

import trafilatura

from odoo import _
from odoo.exceptions import UserError

from odoo.addons.component.core import Component


class TrafilaturaExtractor(Component):
    _name = "llm.trafilatura.extractor"
    _inherit = "llm.resource.extractor.component"
    _usage = "trafilatura"
    _input = "url"
    _output_format = "md"

    def extract(self, resource):
        downloaded = trafilatura.fetch_url(resource.source_url)
        text = trafilatura.extract(
            downloaded,
            include_comments=False,
            include_tables=True,
        )
        if not text:
            raise UserError(
                _("No extractable content found at '%s'.", resource.source_url)
            )
        return text
