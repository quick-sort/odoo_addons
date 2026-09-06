"""MarkItDown file extractor."""

import os
import tempfile

from markitdown import MarkItDown

from odoo.addons.component.core import Component


class MarkitdownExtractor(Component):
    _name = "llm.markitdown.extractor"
    _inherit = "llm.resource.extractor.component"
    _usage = "markitdown"
    _input = "file"
    _output_format = "md"

    def extract(self, resource):
        content = resource._read_source_bytes()
        suffix = os.path.splitext(resource.source_path or "")[1] or ".bin"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        try:
            result = MarkItDown().convert(tmp_path)
            return result.text_content or ""
        finally:
            os.unlink(tmp_path)
