# Copyright 2026 Rui
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

"""Base class for knowledge extractor components."""

from odoo.addons.component.core import AbstractComponent


class KnowledgeExtractorComponent(AbstractComponent):
    _name = "knowledge.extractor.component"
    _collection = "knowledge.extractor"

    # Kind of source this extractor consumes: file or url.
    _input = "file"
    # Output file format: md (markitdown, trafilatura) or json (mineru).
    _output_format = "md"

    def extract(self, source):
        """Extract ``source`` (a knowledge.source record) and return the
        content as ``str`` (md) or a JSON-serializable ``dict``/``list``."""
        raise NotImplementedError

    def validate_config(self):
        """Optional connectivity self-test. Raise on failure."""
