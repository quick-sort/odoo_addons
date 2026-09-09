"""MarkItDown binary-envelope extractor."""

import os
import tempfile

from markitdown import MarkItDown

from odoo.addons.component.core import Component


class MarkitdownExtractor(Component):
    _name = "llm.markitdown.extractor"
    _inherit = "llm.document.extractor.component"
    _usage = "markitdown"

    def extract(self, envelope):
        content = envelope["content"]
        suffix = os.path.splitext(envelope.get("filename") or "")[1] or ".bin"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as temporary:
            temporary.write(content)
            temporary_path = temporary.name
        try:
            result = MarkItDown().convert(temporary_path)
            return result.text_content or ""
        finally:
            os.unlink(temporary_path)
