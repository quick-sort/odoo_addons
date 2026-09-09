import logging
import mimetypes
import os

from odoo import _, fields, models

_logger = logging.getLogger(__name__)


class LLMDocumentFileUrl(models.Model):
    """Resolve an extractor and convert a retrieved binary envelope to Markdown."""

    _inherit = "llm.document"

    extractor_id = fields.Many2one(
        "llm.document.extractor",
        string="Extractor Override",
        ondelete="restrict",
        help="Highest-priority override. Otherwise collection mappings are tried, "
        "then global mappings.",
    )

    def _mapping_match_rank(self, mapping, mimetype, extension):
        mapping_mime = (mapping.mimetype or "").split(";", 1)[0].strip().lower()
        mapping_extension = (mapping.extension or "").strip().lower().lstrip(".")
        if mapping_mime and "*" not in mapping_mime and mapping_mime == mimetype:
            return 0
        if mapping_extension and mapping_extension == extension:
            return 1
        if mapping_mime.endswith("/*") and mimetype.startswith(mapping_mime[:-1]):
            return 2
        if not mapping_mime and not mapping_extension:
            return 3
        return None

    def _matching_extractor_from_scope(self, collection):
        self.ensure_one()
        filename = self.filename or self._inferred_filename()
        mimetype = self._inferred_mimetype(filename)
        extension = os.path.splitext(filename or "")[1].lower().lstrip(".")
        if not extension:
            guessed_extension = mimetypes.guess_extension(mimetype) or ""
            extension = guessed_extension.lstrip(".").lower()

        domain = [("active", "=", True)]
        domain.append(
            ("collection_id", "=", collection.id) if collection else ("collection_id", "=", False)
        )
        mappings = self.env["llm.document.extractor.mapping"].search(
            domain, order="sequence, id"
        )
        ranked = []
        for mapping in mappings:
            rank = self._mapping_match_rank(mapping, mimetype, extension)
            if rank is not None:
                ranked.append((rank, mapping.sequence, mapping.id, mapping))
        if not ranked:
            return self.env["llm.document.extractor"]
        return min(ranked, key=lambda item: item[:3])[3].extractor_id

    def _get_extractor(self):
        self.ensure_one()
        if self.extractor_id:
            return self.extractor_id
        extractor = self._matching_extractor_from_scope(self.collection_id)
        if extractor:
            return extractor
        return self._matching_extractor_from_scope(False)

    def extract(self):
        candidates = self.filtered(lambda document: document.state == "retrieved")
        locked = candidates._lock(state_filter="retrieved")
        successful = self.env["llm.document"]
        for document in locked:
            try:
                extractor = document._get_extractor()
                if not extractor:
                    raise ValueError(
                        _(
                            "No extractor mapping matches MIME '%(mime)s' or filename "
                            "'%(filename)s'. Configure a collection or global mapping, "
                            "or set an extractor override.",
                            mime=document._inferred_mimetype(),
                            filename=document._inferred_filename(),
                        )
                    )
                adapter = extractor._get_adapter()
                if adapter is None:
                    raise ValueError(
                        _(
                            "Extractor '%(name)s' is unavailable. Install the addon "
                            "providing type '%(type)s'.",
                            name=extractor.name,
                            type=extractor.extractor_type,
                        )
                    )
                envelope = document._load_retrieved_envelope()
                markdown = adapter.extract(envelope)
                document._write_processed_markdown(markdown, extractor)
                document._post_styled_message(
                    _("Markdown extracted with %s.", extractor.name), "success"
                )
                successful |= document
            except Exception as error:  # noqa: BLE001
                _logger.exception("Extraction failed for document %s", document.id)
                document.write({"processing_error": str(error)})
                document._post_styled_message(
                    _("Extraction failed: %s", str(error)), "error"
                )
            finally:
                document._unlock()
        return bool(successful)
