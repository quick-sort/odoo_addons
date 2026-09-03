"""Base class for llm.resource extractor components."""

from odoo.addons.component.core import AbstractComponent


class LLMResourceExtractorComponent(AbstractComponent):
    _name = "llm.resource.extractor.component"
    _collection = "llm.resource.extractor"

    # Kind of source this extractor consumes: "file" or "url".
    _input = "file"
    # Output format: "md" (markitdown, trafilatura) or "json" (mineru).
    _output_format = "md"

    def extract(self, resource):
        """Extract ``resource`` (an llm.resource record) and return the
        content as ``str`` (md) or a JSON-serializable ``dict``/``list``."""
        raise NotImplementedError

    def validate_config(self):
        """Optional connectivity self-test. Raise on failure."""
