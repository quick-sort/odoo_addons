# Copyright 2026 Rui
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

"""Content item of a knowledge base: either a one_storage file or a URL.

Extraction writes the result to the KB's ``md_backend_id`` under
``<source.id>/content.md`` (markitdown/trafilatura) or
``<source.id>/content.json`` (mineru). Chunks then live under
``<source.id>/chunks/<chunkset.id>/<seq>.md`` (see knowledge_base_vector_store).
"""

import json
import logging

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class KnowledgeSource(models.Model):
    _name = "knowledge.source"
    _description = "Knowledge Source"
    _order = "kb_id, sequence, id"
    _inherit = ["mail.thread"]

    kb_id = fields.Many2one(
        comodel_name="knowledge.base",
        string="Knowledge Base",
        required=True,
        ondelete="cascade",
        index=True,
    )
    source_type = fields.Selection(
        selection=[("file", "File"), ("url", "URL")],
        required=True,
        default="file",
    )
    entry_id = fields.Many2one(
        comodel_name="one.storage.entry",
        string="Storage Entry",
        ondelete="restrict",
        index=True,
    )
    url = fields.Char(string="URL")
    name = fields.Char(compute="_compute_name", store=True)
    sequence = fields.Integer(default=10)
    extractor_id = fields.Many2one(
        comodel_name="knowledge.extractor",
        string="Extractor Override",
        ondelete="restrict",
    )
    state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("queued", "Queued"),
            ("extracting", "Extracting"),
            ("extracted", "Extracted"),
            ("error", "Error"),
        ],
        default="draft",
    )
    output_format = fields.Char(
        compute="_compute_output_format",
        help="Output file format of the configured extractor: md or json.",
    )
    content_path = fields.Char(
        compute="_compute_content_path",
        help="Path of the extraction result inside the KB's md backend.",
    )
    last_extraction = fields.Datetime()

    @api.depends("entry_id.name", "url")
    def _compute_name(self):
        for source in self:
            if source.entry_id:
                source.name = source.entry_id.name
            elif source.url:
                source.name = source.url
            else:
                source.name = False

    @api.depends("extractor_id.extractor_type", "kb_id.extractor_id.extractor_type")
    def _compute_output_format(self):
        for source in self:
            extractor = source._get_extractor()
            source.output_format = (
                extractor._get_output_format() if extractor else False
            )

    def _compute_content_path(self):
        for source in self:
            source.content_path = (
                "%s/content.%s" % (source.id, source.output_format or "md")
                if source.id
                else False
            )

    @api.constrains("source_type", "entry_id", "url")
    def _check_source_reference(self):
        for source in self:
            if source.source_type == "file" and not source.entry_id:
                raise ValidationError(
                    _("A file source must reference a one_storage entry.")
                )
            if source.source_type == "url" and not source.url:
                raise ValidationError(_("A URL source must have a URL."))

    @api.constrains("extractor_id", "source_type")
    def _check_extractor_compatibility(self):
        for source in self:
            extractor = source.extractor_id or source.kb_id.extractor_id
            if not extractor:
                continue
            adapter = extractor._get_adapter()
            if adapter is None:
                continue
            expected = getattr(adapter, "_input", "file")
            if expected != source.source_type:
                raise ValidationError(
                    _(
                        "Extractor '%s' cannot process '%s' sources.",
                        extractor.name,
                        source.source_type,
                    )
                )

    # ------------------------------------------------------------------
    # Extraction helpers
    # ------------------------------------------------------------------
    def _get_extractor(self):
        """Return the effective extractor: source override or KB default."""
        self.ensure_one()
        return self.extractor_id or self.kb_id.extractor_id

    def _content(self):
        """Return the raw content bytes of a file source."""
        self.ensure_one()
        if self.source_type != "file":
            return None
        entry = self.entry_id
        if not entry:
            raise ValidationError(
                _("Source '%s' has no storage entry.", self.name)
            )
        return entry.read_bytes()

    def _extract(self):
        """Run extraction for this source. Queue job body."""
        self.ensure_one()
        extractor = self._get_extractor()
        if not extractor:
            self.write({"state": "error"})
            return
        adapter = extractor._get_adapter()
        if adapter is None:
            self.write({"state": "error"})
            return
        self.write({"state": "extracting"})
        try:
            output = adapter.extract(self)
        except Exception:  # noqa: BLE001
            _logger.exception("Extraction failed for source %s", self.name)
            self.write({"state": "error"})
            self.kb_id._refresh_state()
            return
        fmt = getattr(adapter, "_output_format", "md") or "md"
        path = "%s/content.%s" % (self.id, fmt)
        if fmt == "json" and not isinstance(output, (str, bytes)):
            output = json.dumps(output, ensure_ascii=False, default=str)
        if isinstance(output, str):
            output = output.encode("utf-8")
        with self.kb_id.md_backend_id.open(path, "wb") as stream:
            stream.write(output)
        self.write(
            {"state": "extracted", "last_extraction": fields.Datetime.now()}
        )
        self.kb_id._refresh_state()
