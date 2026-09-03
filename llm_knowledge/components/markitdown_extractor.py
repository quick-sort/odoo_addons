"""MarkItDown extractor: converts office/pdf/html files to markdown locally.

The 'markitdown' package is imported lazily so the addon installs even when
it is not present; a clear error is raised at extraction time instead.
"""

import logging
import os
import tempfile

from odoo import _
from odoo.exceptions import UserError

from odoo.addons.component.core import Component

_logger = logging.getLogger(__name__)


class MarkitdownExtractor(Component):
    _name = "llm.markitdown.extractor"
    _inherit = "llm.resource.extractor.component"
    _usage = "markitdown"
    _input = "file"
    _output_format = "md"

    def extract(self, resource):
        try:
            from markitdown import MarkItDown
        except ImportError as err:
            raise UserError(
                _(
                    "The 'markitdown' python package is required for the "
                    "MarkItDown extractor. Install it with: pip install markitdown"
                )
            ) from err
        content = resource._read_source_bytes()
        suffix = os.path.splitext(resource.entry_id.name or "")[1] or ".bin"
        with tempfile.NamedTemporaryFile(suffix=suffix, delete=False) as tmp:
            tmp.write(content)
            tmp_path = tmp.name
        try:
            result = MarkItDown().convert(tmp_path)
            return result.text_content or ""
        finally:
            os.unlink(tmp_path)
