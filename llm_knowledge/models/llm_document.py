import hashlib
import logging
import mimetypes
import os
from datetime import timedelta
from urllib.parse import unquote, urlparse

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class LLMDocument(models.Model):
    """A file or URL processed as binary envelope -> Markdown."""

    _name = "llm.document"
    _description = "LLM Document for Document Management"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    _unique_file_reference = models.Constraint(
        "UNIQUE(collection_id, source_type, source_backend_id, source_path)",
        "This collection already contains a document for this file.",
    )
    _unique_url_reference = models.Constraint(
        "UNIQUE(collection_id, source_type, source_url)",
        "This collection already contains a document for this URL.",
    )

    name = fields.Char(required=True, tracking=True)
    collection_id = fields.Many2one(
        "llm.knowledge.collection",
        string="Collection",
        required=True,
        ondelete="cascade",
        index=True,
        tracking=True,
    )
    source_type = fields.Selection(
        [("file", "File"), ("url", "URL")],
        default="file",
        required=True,
        tracking=True,
    )
    source_backend_id = fields.Many2one(
        "storage.backend",
        string="Source Backend",
        ondelete="restrict",
        index=True,
    )
    source_path = fields.Char(string="Source Path")
    source_url = fields.Char(string="Source URL")

    filename = fields.Char(readonly=True, tracking=True)
    mimetype = fields.Char(readonly=True, tracking=True)
    size = fields.Integer(string="Source Size", readonly=True)
    checksum = fields.Char(string="Source SHA-256", readonly=True, index=True)
    final_url = fields.Char(readonly=True)
    etag = fields.Char(string="ETag", readonly=True)
    last_modified = fields.Char(readonly=True)
    retrieved_at = fields.Datetime(readonly=True)

    raw_cache_path = fields.Char(
        compute="_compute_cache_paths",
        store=True,
        readonly=True,
        help="URL source binary path in the collection cache backend.",
    )
    markdown_cache_path = fields.Char(
        compute="_compute_cache_paths",
        store=True,
        readonly=True,
        help="Processed Markdown path in the collection cache backend.",
    )
    markdown = fields.Text(
        string="Processed Markdown",
        help="Inline copy of the processed Markdown; the cache backend copy is "
        "authoritative when configured.",
    )
    processed_size = fields.Integer(readonly=True)
    processed_checksum = fields.Char(string="Markdown SHA-256", readonly=True)
    processed_at = fields.Datetime(readonly=True)
    processed_metadata = fields.Json(default=dict, readonly=True)
    processing_error = fields.Text(readonly=True)

    state = fields.Selection(
        [("draft", "Draft"), ("retrieved", "Retrieved"), ("processed", "Processed")],
        default="draft",
        required=True,
        tracking=True,
    )
    lock_date = fields.Datetime(
        tracking=True,
        help="Date when the document was locked for processing.",
    )
    to_delete = fields.Boolean(
        tracking=True,
        help="The source file was absent during the last storage scan.",
    )
    kanban_state = fields.Selection(
        [("normal", "Ready"), ("blocked", "Blocked"), ("done", "Done")],
        compute="_compute_kanban_state",
        store=True,
    )

    @api.depends("collection_id", "source_type")
    def _compute_cache_paths(self):
        for document in self:
            if not document.id or not document.collection_id:
                document.raw_cache_path = False
                document.markdown_cache_path = False
                continue
            prefix = "collections/%s/documents/%s" % (
                document.collection_id.id,
                document.id,
            )
            document.raw_cache_path = (
                "%s/source.bin" % prefix if document.source_type == "url" else False
            )
            document.markdown_cache_path = "%s/content.md" % prefix

    @api.constrains(
        "source_type", "source_backend_id", "source_path", "source_url", "collection_id"
    )
    def _check_source_reference(self):
        for document in self:
            if document.source_type == "file" and (
                not document.source_backend_id or not document.source_path
            ):
                raise UserError(
                    _(
                        "Document '%s': a file source requires a source backend and path.",
                        document.name,
                    )
                )
            if document.source_type == "url":
                if not document.source_url:
                    raise UserError(
                        _("Document '%s': a URL source requires a URL.", document.name)
                    )
                if not document.collection_id.cache_backend_id:
                    raise UserError(
                        _(
                            "Collection '%s' needs a cache backend before URL documents "
                            "can be retrieved.",
                            document.collection_id.name,
                        )
                    )

    @api.depends("lock_date")
    def _compute_kanban_state(self):
        for document in self:
            document.kanban_state = "blocked" if document.lock_date else "normal"

    def _cache_backend(self):
        self.ensure_one()
        return self.collection_id.cache_backend_id

    def _source_uri(self):
        self.ensure_one()
        if self.source_type == "url":
            return self.final_url or self.source_url
        return "storage://%s/%s" % (self.source_backend_id.id, self.source_path)

    def _inferred_filename(self):
        self.ensure_one()
        if self.filename:
            return self.filename
        if self.source_type == "file":
            return os.path.basename(self.source_path or "") or self.name
        path = unquote(urlparse(self.final_url or self.source_url or "").path)
        return os.path.basename(path) or self.name or "download"

    def _inferred_mimetype(self, filename=None):
        self.ensure_one()
        current = (self.mimetype or "").split(";", 1)[0].strip().lower()
        if current and current != "application/octet-stream":
            return current
        guessed, _encoding = mimetypes.guess_type(filename or self._inferred_filename())
        return guessed or current or "application/octet-stream"

    def _make_envelope(self, content, **metadata):
        self.ensure_one()
        if not isinstance(content, bytes):
            raise UserError(_("Retriever output must contain binary content."))
        filename = metadata.get("filename") or self._inferred_filename()
        mimetype = (
            metadata.get("mimetype") or self._inferred_mimetype(filename)
        ).split(";", 1)[0].strip().lower()
        return {
            "content": content,
            "filename": filename,
            "mimetype": mimetype or "application/octet-stream",
            "size": len(content),
            "checksum": hashlib.sha256(content).hexdigest(),
            "source_uri": metadata.get("source_uri") or self._source_uri(),
            "final_url": metadata.get("final_url", self.final_url) or False,
            "etag": metadata.get("etag", self.etag) or False,
            "last_modified": metadata.get("last_modified", self.last_modified)
            or False,
            "retrieved_at": fields.Datetime.now(),
        }

    def _persist_envelope_metadata(self, envelope):
        self.ensure_one()
        self.write(
            {
                "filename": envelope["filename"],
                "mimetype": envelope["mimetype"],
                "size": envelope["size"],
                "checksum": envelope["checksum"],
                "final_url": envelope.get("final_url") or False,
                "etag": envelope.get("etag") or False,
                "last_modified": envelope.get("last_modified") or False,
                "retrieved_at": envelope["retrieved_at"],
                "processing_error": False,
            }
        )

    def _retrieve_file_binary(self):
        self.ensure_one()
        with self.source_backend_id.open(self.source_path, "rb") as stream:
            content = stream.read()
        return self._make_envelope(
            content,
            filename=os.path.basename(self.source_path),
            source_uri=self._source_uri(),
        )

    def _read_cached_url_binary(self):
        self.ensure_one()
        backend = self._cache_backend()
        if not backend or not self.raw_cache_path:
            return None
        if not backend.file_exists(self.raw_cache_path):
            return None
        with backend.open(self.raw_cache_path, "rb") as stream:
            return stream.read()

    def _retrieve_url_binary(self, force_refresh=False):
        self.ensure_one()
        backend = self._cache_backend()
        cached = self._read_cached_url_binary()
        if cached is not None and not force_refresh:
            return self._make_envelope(
                cached,
                filename=self.filename or self._inferred_filename(),
                mimetype=self.mimetype or self._inferred_mimetype(),
                final_url=self.final_url or self.source_url,
                etag=self.etag,
                last_modified=self.last_modified,
            )

        downloaded = self._download_url(force_refresh=force_refresh)
        if downloaded.get("not_modified"):
            if cached is None:
                raise UserError(_("The URL returned 304 but no cached binary exists."))
            return self._make_envelope(
                cached,
                filename=self.filename or self._inferred_filename(),
                mimetype=self.mimetype or self._inferred_mimetype(),
                final_url=self.final_url or self.source_url,
                etag=downloaded.get("etag") or self.etag,
                last_modified=downloaded.get("last_modified") or self.last_modified,
            )

        downloaded = dict(downloaded)
        content = downloaded.pop("content", None)
        envelope = self._make_envelope(content, **downloaded)
        with backend.open(self.raw_cache_path, "wb") as stream:
            stream.write(content)
        return envelope

    def _retrieve_binary(self, force_refresh=False):
        self.ensure_one()
        if self.source_type == "file":
            return self._retrieve_file_binary()
        return self._retrieve_url_binary(force_refresh=force_refresh)

    def _load_retrieved_envelope(self):
        self.ensure_one()
        if self.source_type == "file":
            return self._retrieve_file_binary()
        content = self._read_cached_url_binary()
        if content is None:
            raise UserError(
                _(
                    "Cached URL binary is missing for '%s'. Force refresh the document.",
                    self.name,
                )
            )
        return self._make_envelope(
            content,
            filename=self.filename or self._inferred_filename(),
            mimetype=self.mimetype or self._inferred_mimetype(),
            final_url=self.final_url or self.source_url,
            etag=self.etag,
            last_modified=self.last_modified,
        )

    def retrieve(self, force_refresh=False):
        candidates = self.filtered(lambda document: document.state == "draft")
        locked = candidates._lock(state_filter="draft")
        successful = self.env["llm.document"]
        for document in locked:
            try:
                envelope = document._retrieve_binary(force_refresh=force_refresh)
                document._persist_envelope_metadata(envelope)
                document.write({"state": "retrieved"})
                document._post_styled_message(_("Binary source retrieved."), "success")
                successful |= document
            except Exception as error:  # noqa: BLE001
                _logger.exception("Error retrieving document %s", document.id)
                document.write({"processing_error": str(error)})
                document._post_styled_message(
                    _("Retrieval failed: %s", str(error)), "error"
                )
            finally:
                document._unlock()
        return bool(successful)

    def _write_processed_markdown(self, markdown_text, extractor):
        self.ensure_one()
        if not isinstance(markdown_text, str):
            raise UserError(
                _(
                    "Extractor '%s' returned %s; extractors must return Markdown str.",
                    extractor.name,
                    type(markdown_text).__name__,
                )
            )
        data = markdown_text.encode("utf-8")
        backend = self._cache_backend()
        if backend and self.markdown_cache_path:
            with backend.open(self.markdown_cache_path, "wb") as stream:
                stream.write(data)
        metadata = {
            "document_id": self.id,
            "document_name": self.name,
            "title": self.name,
            "source_uri": self._source_uri(),
            "mimetype": self.mimetype,
            "filename": self.filename,
            "checksum": self.checksum,
            "extractor_id": extractor.id,
            "extractor": extractor.name,
        }
        self.write(
            {
                "markdown": markdown_text,
                "processed_size": len(data),
                "processed_checksum": hashlib.sha256(data).hexdigest(),
                "processed_at": fields.Datetime.now(),
                "processed_metadata": metadata,
                "processing_error": False,
                "state": "processed",
            }
        )

    def _read_processed_markdown(self):
        self.ensure_one()
        backend = self._cache_backend()
        if (
            backend
            and self.markdown_cache_path
            and backend.file_exists(self.markdown_cache_path)
        ):
            with backend.open(self.markdown_cache_path, "rb") as stream:
                return stream.read().decode("utf-8")
        return self.markdown or ""

    def get_processed_document(self):
        """Return the complete processed document contract used for splitting."""
        self.ensure_one()
        markdown = self._read_processed_markdown()
        metadata = dict(self.processed_metadata or {})
        metadata.update(
            {
                "document_id": self.id,
                "document_name": self.name,
                "collection_id": self.collection_id.id,
                "source_type": self.source_type,
                "source_uri": self._source_uri(),
                "final_url": self.final_url or False,
                "etag": self.etag or False,
                "last_modified": self.last_modified or False,
                "retrieved_at": fields.Datetime.to_string(self.retrieved_at)
                if self.retrieved_at
                else False,
                "processed_at": fields.Datetime.to_string(self.processed_at)
                if self.processed_at
                else False,
                "processed_checksum": self.processed_checksum or False,
            }
        )
        return {
            "title": self.name,
            "source_uri": self._source_uri(),
            "mimetype": self.mimetype or "application/octet-stream",
            "filename": self.filename or self._inferred_filename(),
            "checksum": self.checksum,
            "markdown": markdown,
            "metadata": metadata,
        }

    def process_document(self, force_refresh=False):
        draft_documents = self.filtered(lambda document: document.state == "draft")
        if draft_documents:
            draft_documents.retrieve(force_refresh=force_refresh)
        retrieved_documents = self.filtered(
            lambda document: document.state == "retrieved"
        )
        if retrieved_documents:
            retrieved_documents.extract()
        return True

    def _invalidate_indexed_content(self):
        """Extension hook for downstream chunk and vector cleanup."""
        return True

    def action_force_refresh(self):
        self.write({"state": "draft", "lock_date": False, "processing_error": False})
        return self.process_document(force_refresh=True)

    def action_open_document(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "llm.document",
            "res_id": self.id,
            "view_mode": "form",
            "target": "current",
        }

    @api.model
    def action_mass_process_documents(self):
        documents = self.browse(self.env.context.get("active_ids", []))
        if not documents:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("No Documents Selected"),
                    "message": _("Please select documents to process."),
                    "type": "warning",
                    "sticky": False,
                },
            }
        documents.process_document()
        return {"type": "ir.actions.client", "tag": "reload"}

    def action_mass_unlock(self):
        self._unlock()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Documents Unlocked"),
                "message": _("%(count)s documents have been unlocked", count=len(self)),
                "type": "success",
                "sticky": False,
            },
        }

    def action_mass_reset(self):
        documents = self.browse(self.env.context.get("active_ids", []))
        documents.filtered(lambda document: document.state != "draft").write(
            {"state": "draft", "lock_date": False, "processing_error": False}
        )
        return {"type": "ir.actions.client", "tag": "reload"}

    def _lock(self, state_filter=None, stale_lock_minutes=10):
        now = fields.Datetime.now()
        domain = [
            ("id", "in", self.ids),
            "|",
            ("lock_date", "=", False),
            ("lock_date", "<", now - timedelta(minutes=stale_lock_minutes)),
        ]
        if state_filter:
            domain.append(("state", "=", state_filter))
        documents = self.env["llm.document"].search(domain)
        if documents:
            documents.write({"lock_date": now})
        return documents

    def _unlock(self):
        return self.write({"lock_date": False})

    def _reset_state_if_needed(self):
        self.ensure_one()
        return True

    def write(self, vals):
        old_collections = {}
        if "collection_id" in vals:
            old_collections = {document.id: document.collection_id for document in self}
        result = super().write(vals)
        if "collection_id" in vals:
            for document in self:
                old_collection = old_collections.get(document.id)
                if old_collection and old_collection != document.collection_id:
                    old_collection._handle_removed_documents([document.id])
        return result
