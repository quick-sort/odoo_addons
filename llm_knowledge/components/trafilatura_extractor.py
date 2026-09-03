"""Trafilatura extractor: fetches a URL and extracts the main article to
markdown. The 'trafilatura' package is imported lazily.
"""

import logging

from odoo import _
from odoo.exceptions import UserError

from odoo.addons.component.core import Component

_logger = logging.getLogger(__name__)


class TrafilaturaExtractor(Component):
    _name = "llm.trafilatura.extractor"
    _inherit = "llm.resource.extractor.component"
    _usage = "trafilatura"
    _input = "url"
    _output_format = "md"

    def extract(self, resource):
        try:
            import trafilatura
        except ImportError as err:
            raise UserError(
                _(
                    "The 'trafilatura' python package is required for the "
                    "Trafilatura extractor. Install it with: pip install trafilatura"
                )
            ) from err
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
