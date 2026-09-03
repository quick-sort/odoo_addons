import json
import logging

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)


class LLMResourceFileUrl(models.Model):
    """Retrieval/parsing for file- and URL-type resources via the
    ``llm.resource.extractor`` component-adapter pattern (markitdown, mineru,
    trafilatura, ...), mirroring how ``knowledge.source._extract()`` worked
    in the knowledge_base addon.

    For ``source_type='record'`` resources this mixin is a no-op; the
    existing polymorphic retrieve()/parse() flow (llm_resource_retriever.py,
    llm_resource_parser.py) is unchanged.
    """

    _inherit = "llm.resource"

    extractor_id = fields.Many2one(
        "llm.resource.extractor",
        string="Extractor Override",
        ondelete="restrict",
        help="Extractor used for file/url resources. If unset, the first "
        "extractor compatible with this resource's source_type is used.",
    )

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("source_type") in ("file", "url") and not vals.get(
                "retriever"
            ):
                vals["retriever"] = "extractor"
        return super().create(vals_list)

    def _get_extractor(self):
        """Return the effective extractor for a file/url resource."""
        self.ensure_one()
        if self.extractor_id:
            return self.extractor_id
        extractors = self.env["llm.resource.extractor"].search(
            [("active", "=", True)]
        )
        for extractor in extractors:
            adapter = extractor._get_adapter()
            if adapter is not None and getattr(adapter, "_input", "file") == (
                "url" if self.source_type == "url" else "file"
            ):
                return extractor
        return self.env["llm.resource.extractor"]

    def retrieve(self):
        """Override retrieve() to branch file/url resources away from the
        record-based flow (which requires model_id/res_id to browse a
        backing record) straight into the extractor pipeline."""
        file_url_resources = self.filtered(lambda r: r.source_type in ("file", "url"))
        record_resources = self - file_url_resources

        any_success = False
        if file_url_resources:
            draft = file_url_resources.filtered(lambda r: r.state == "draft")
            locked = draft._lock()
            successful = self.env["llm.resource"]
            for resource in locked:
                try:
                    result = resource._extract_and_parse()
                    if result:
                        resource.write({"state": result.get("state", "retrieved")})
                        successful |= resource
                    else:
                        resource._unlock()
                except Exception as exc:  # noqa: BLE001
                    _logger.error(
                        "Error retrieving resource %s: %s", resource.id, exc
                    )
                    resource._post_styled_message(
                        _("Error retrieving resource: %s", str(exc)), "error"
                    )
                    resource._unlock()
            successful._unlock()
            any_success = any_success or bool(successful)

        if record_resources:
            any_success = (
                super(LLMResourceFileUrl, record_resources).retrieve() or any_success
            )

        return any_success

    def _extract_and_parse(self):
        """Run the extractor synchronously and write markdown straight to
        the resource's content_path, going directly to 'parsed' state since
        extraction already yields markdown/text (no separate parse step
        needed, unlike record-type resources which parse raw field data)."""
        self.ensure_one()
        extractor = self._get_extractor()
        if not extractor:
            self._post_styled_message(
                _("No extractor configured for '%s' sources.", self.source_type),
                "error",
            )
            return False
        adapter = extractor._get_adapter()
        if adapter is None:
            self._post_styled_message(
                _("Extractor '%s' has no working adapter.", extractor.name), "error"
            )
            return False
        try:
            output = adapter.extract(self)
        except Exception as exc:  # noqa: BLE001
            _logger.exception("Extraction failed for resource %s", self.id)
            self._post_styled_message(_("Extraction failed: %s", str(exc)), "error")
            return False

        fmt = getattr(adapter, "_output_format", "md") or "md"
        if fmt == "json" and not isinstance(output, str):
            text = json.dumps(output, ensure_ascii=False, default=str, indent=2)
        else:
            text = output or ""
        self._write_content_to_backend(text)
        return {"state": "parsed"}

    def parse(self):
        """Override parse() to skip file/url resources: their content is
        already markdown/text once retrieve_extractor() has run, so they
        move straight from 'retrieved' to 'parsed' without field-based
        parsing (which only applies to source_type='record')."""
        file_url_resources = self.filtered(lambda r: r.source_type in ("file", "url"))
        record_resources = self - file_url_resources

        if file_url_resources:
            locked = file_url_resources._lock(state_filter="retrieved")
            for resource in locked:
                resource.write({"state": "parsed"})
            locked._unlock()

        if record_resources:
            return super(LLMResourceFileUrl, record_resources).parse()
        return True
