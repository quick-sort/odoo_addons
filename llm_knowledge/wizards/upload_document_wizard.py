import base64
import logging
import os
import posixpath
import re
from urllib.parse import urlparse

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class UploadDocumentWizard(models.TransientModel):
    _name = "llm.upload.document.wizard"
    _description = "Upload RAG Documents Wizard"

    collection_id = fields.Many2one(
        "llm.knowledge.collection",
        string="Collection",
        required=True,
        help="Collection to which documents will be added",
    )
    file_ids = fields.Many2many(
        "ir.attachment", string="Files", help="Local files to upload"
    )
    external_urls = fields.Text(
        string="External URLs", help="External URLs to include, one per line"
    )
    document_name_template = fields.Char(
        string="Document Name Template",
        default="{filename}",
        help="Template for document names. Use {filename}, {collection}, and {index} as placeholders.",
        required=True,
    )
    process_immediately = fields.Boolean(
        string="Process Immediately",
        default=False,
        help="If checked, documents will be immediately processed through the RAG pipeline",
    )
    state = fields.Selection(
        [
            ("confirm", "Confirm"),
            ("done", "Done"),
        ],
        default="confirm",
    )
    created_document_ids = fields.Many2many(
        "llm.document",
        string="Created Documents",
    )
    created_count = fields.Integer(string="Created", compute="_compute_created_count")

    @api.depends("created_document_ids")
    def _compute_created_count(self):
        for wizard in self:
            wizard.created_count = len(wizard.created_document_ids)

    def _extract_filename_from_url(self, url):
        """Extract a filename from a URL, handling query parameters."""
        parsed_url = urlparse(url)
        filename = (
            os.path.basename(parsed_url.path)
            if parsed_url.path
            else "document_from_url"
        )
        filename = re.sub(r"[?#].*", "", filename)
        filename = re.sub(r'[\\/:*?"<>|]', "_", filename)
        return filename[:100] or "document_from_url"

    def _process_file_uploads(self, collection):
        """Copy uploaded files to source storage and create file documents."""
        self.ensure_one()
        created_documents = self.env["llm.document"]
        if not self.file_ids:
            return created_documents

        backend = collection.source_backend_id
        if not backend:
            raise UserError(
                _(
                    "Collection '%s' has no source storage backend configured "
                    "for file uploads.",
                    collection.name,
                )
            )
        upload_dir = posixpath.join(
            collection._get_source_prefix(), "llm_knowledge_uploads"
        )
        for index, attachment in enumerate(self.file_ids):
            filename = self._extract_filename_from_url(
                attachment.name or f"file_{index + 1}"
            )
            document_name = self.document_name_template.format(
                filename=filename,
                collection=collection.name,
                index=index + 1,
            )
            path = posixpath.join(upload_dir, f"{attachment.id}_{filename}")
            with backend.open(path, "wb") as stream:
                stream.write(base64.b64decode(attachment.datas or b""))
            created_documents |= self.env["llm.document"].create(
                {
                    "name": document_name,
                    "source_type": "file",
                    "source_backend_id": backend.id,
                    "source_path": path,
                    "collection_id": collection.id,
                }
            )
        return created_documents

    def _process_external_urls(self, collection, file_count):
        """Create URL documents for processing by an installed URL extractor."""
        self.ensure_one()
        created_documents = self.env["llm.document"]
        urls = [
            url.strip()
            for url in (self.external_urls or "").splitlines()
            if url.strip()
        ]
        if urls and not collection.cache_backend_id:
            raise UserError(
                _(
                    "Collection '%s' needs a cache backend before URL documents "
                    "can be uploaded.",
                    collection.name,
                )
            )
        for index, url in enumerate(urls):
            filename = self._extract_filename_from_url(url)
            document_name = self.document_name_template.format(
                filename=filename,
                collection=collection.name,
                index=file_count + index + 1,
            )
            try:
                created_documents |= self.env["llm.document"].create(
                    {
                        "name": document_name,
                        "source_type": "url",
                        "source_url": url,
                        "collection_id": collection.id,
                    }
                )
            except Exception:  # noqa: BLE001
                _logger.exception("Failed to create llm.document for URL %s", url)

        return created_documents

    def action_upload_documents(self):
        """Create native file/URL documents and optionally process them."""
        self.ensure_one()
        collection = self.collection_id

        if not self.file_ids and not self.external_urls:
            raise UserError(_("Please provide at least one file or URL"))

        file_documents = self._process_file_uploads(collection)
        url_documents = self._process_external_urls(collection, len(self.file_ids))
        created_documents = file_documents | url_documents

        if self.process_immediately and created_documents:
            _logger.info("Processing %s documents immediately.", len(created_documents))
            for document in created_documents:
                try:
                    document.process_document()
                except Exception as error:  # noqa: BLE001
                    _logger.error(
                        "Error processing document %s (%s): %s",
                        document.id,
                        document.name,
                        error,
                        exc_info=True,
                    )
                    document._post_styled_message(
                        _("Processing failed: %s", str(error)), "error"
                    )

        self.write(
            {
                "state": "done",
                "created_document_ids": [(6, 0, created_documents.ids)],
            }
        )
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
            "context": self.env.context,
        }

    def action_view_documents(self):
        """Open the created documents."""
        return {
            "name": _("Uploaded RAG Documents"),
            "type": "ir.actions.act_window",
            "res_model": "llm.document",
            "view_mode": "list,form,kanban",
            "domain": [("id", "in", self.created_document_ids.ids)],
            "view_ids": [
                (5, 0, 0),
                (
                    0,
                    0,
                    {
                        "view_mode": "kanban",
                        "view_id": self.env.ref(
                            "llm_knowledge.view_llm_document_kanban"
                        ).id,
                    },
                ),
                (
                    0,
                    0,
                    {
                        "view_mode": "list",
                        "view_id": self.env.ref(
                            "llm_knowledge.view_llm_document_tree"
                        ).id,
                    },
                ),
                (
                    0,
                    0,
                    {
                        "view_mode": "form",
                        "view_id": self.env.ref(
                            "llm_knowledge.view_llm_document_form"
                        ).id,
                    },
                ),
            ],
            "search_view_id": [
                self.env.ref("llm_knowledge.view_llm_document_search").id
            ],
        }
