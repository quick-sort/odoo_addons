"""Base class for llm.document binary-envelope extractor components."""

from odoo.addons.component.core import AbstractComponent


class LLMDocumentExtractorComponent(AbstractComponent):
    _name = "llm.document.extractor.component"
    _collection = "llm.document.extractor"

    def extract(self, envelope):
        """Return Markdown ``str`` for a retrieved binary envelope.

        ``envelope`` contains ``content`` bytes plus source metadata such as
        filename, mimetype, checksum, source_uri, and HTTP response metadata.
        Extractors must not read llm.document records or perform downloads.
        """
        raise NotImplementedError

    def validate_config(self):
        """Optional connectivity self-test. Raise on failure."""
