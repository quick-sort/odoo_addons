"""Trafilatura binary-envelope extractor."""

import trafilatura

from odoo import _
from odoo.exceptions import UserError

from odoo.addons.component.core import Component


class TrafilaturaExtractor(Component):
    _name = "llm.trafilatura.extractor"
    _inherit = "llm.document.extractor.component"
    _usage = "trafilatura"

    def extract(self, envelope):
        downloaded = envelope["content"].decode("utf-8", errors="replace")
        markdown = trafilatura.extract(
            downloaded,
            include_comments=False,
            include_tables=True,
            output_format="markdown",
            url=envelope.get("final_url") or envelope.get("source_uri"),
        )
        if not markdown:
            raise UserError(
                _(
                    "No extractable content found in '%s'.",
                    envelope.get("filename") or envelope.get("source_uri"),
                )
            )
        return markdown
