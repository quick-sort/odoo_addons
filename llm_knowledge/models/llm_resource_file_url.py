import json
import logging

from odoo import _, fields, models

_logger = logging.getLogger(__name__)


class LLMResourceFileUrl(models.Model):
    """Process file and URL resources with optional extractor components."""

    _inherit = "llm.resource"

    extractor_id = fields.Many2one(
        "llm.resource.extractor",
        string="Extractor Override",
        ondelete="restrict",
        help="Extractor used for file/URL resources. If unset, the first active "
        "installed extractor compatible with the source type is used.",
    )

    def _get_extractor(self):
        self.ensure_one()
        if self.extractor_id:
            return self.extractor_id

        expected_input = "url" if self.source_type == "url" else "file"
        extractors = self.env["llm.resource.extractor"].search(
            [("active", "=", True)], order="id"
        )
        for extractor in extractors:
            adapter = extractor._get_adapter()
            if adapter is not None and getattr(adapter, "_input", "file") == expected_input:
                return extractor
        return self.env["llm.resource.extractor"]

    def retrieve(self):
        file_url_resources = self.filtered(lambda r: r.source_type in ("file", "url"))
        record_resources = self - file_url_resources

        any_success = False
        if file_url_resources:
            locked = file_url_resources.filtered(lambda r: r.state == "draft")._lock()
            successful = self.env["llm.resource"]
            for resource in locked:
                try:
                    result = resource._extract_and_parse()
                    if result:
                        resource.write({"state": result.get("state", "retrieved")})
                        successful |= resource
                    else:
                        resource._unlock()
                except Exception as error:  # noqa: BLE001
                    _logger.exception("Error retrieving resource %s", resource.id)
                    resource._post_styled_message(
                        _("Error retrieving resource: %s", str(error)), "error"
                    )
                    resource._unlock()
            successful._unlock()
            any_success = bool(successful)

        if record_resources:
            any_success = (
                super(LLMResourceFileUrl, record_resources).retrieve() or any_success
            )
        return any_success

    def _extract_and_parse(self):
        self.ensure_one()
        extractor = self._get_extractor()
        if not extractor:
            self._post_styled_message(
                _(
                    "No installed extractor is configured for '%s' sources. "
                    "Install an appropriate llm_knowledge_extractor addon and "
                    "create an extractor record.",
                    self.source_type,
                ),
                "error",
            )
            return False

        adapter = extractor._get_adapter()
        if adapter is None:
            self._post_styled_message(
                _(
                    "Extractor '%s' is unavailable. Install the addon that provides '%s'.",
                    extractor.name,
                    extractor.extractor_type,
                ),
                "error",
            )
            return False

        expected_input = "url" if self.source_type == "url" else "file"
        if getattr(adapter, "_input", "file") != expected_input:
            self._post_styled_message(
                _(
                    "Extractor '%s' does not support '%s' sources.",
                    extractor.name,
                    self.source_type,
                ),
                "error",
            )
            return False

        try:
            output = adapter.extract(self)
        except Exception as error:  # noqa: BLE001
            _logger.exception("Extraction failed for resource %s", self.id)
            self._post_styled_message(
                _("Extraction failed: %s", str(error)), "error"
            )
            return False

        output_format = getattr(adapter, "_output_format", "md") or "md"
        if output_format == "json" and not isinstance(output, str):
            text = json.dumps(output, ensure_ascii=False, default=str, indent=2)
        else:
            text = output or ""
        self._write_content_to_backend(text)
        return {"state": "parsed"}

    def parse(self):
        file_url_resources = self.filtered(lambda r: r.source_type in ("file", "url"))
        record_resources = self - file_url_resources

        if file_url_resources:
            locked = file_url_resources._lock(state_filter="retrieved")
            locked.write({"state": "parsed"})
            locked._unlock()

        if record_resources:
            return super(LLMResourceFileUrl, record_resources).parse()
        return True
