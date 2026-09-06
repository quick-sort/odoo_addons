import base64
import logging
import os
import posixpath
import re
from urllib.parse import urlparse

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class UploadResourceWizard(models.TransientModel):
    _name = "llm.upload.resource.wizard"  # Keep original name or rename if preferred
    _description = "Upload RAG Resources Wizard"

    collection_id = fields.Many2one(
        "llm.knowledge.collection",  # Target llm.knowledge.collection
        string="Collection",
        required=True,  # Collection is required here
        help="Collection to which resources will be added",
    )
    file_ids = fields.Many2many(
        "ir.attachment", string="Files", help="Local files to upload"
    )
    external_urls = fields.Text(
        string="External URLs", help="External URLs to include, one per line"
    )
    # Field renamed for clarity
    resource_name_template = fields.Char(
        string="Resource Name Template",
        default="{filename}",
        help="Template for resource names. Use {filename}, {collection}, and {index} as placeholders.",
        required=True,
    )
    process_immediately = fields.Boolean(
        string="Process Immediately",
        default=False,
        help="If checked, resources will be immediately processed through the RAG pipeline",
    )
    state = fields.Selection(
        [
            ("confirm", "Confirm"),
            ("done", "Done"),
        ],
        default="confirm",
    )
    # Field renamed and target model changed
    created_resource_ids = fields.Many2many(
        "llm.resource",  # Target llm.resource
        string="Created Resources",
    )
    created_count = fields.Integer(string="Created", compute="_compute_created_count")

    @api.depends("created_resource_ids")
    def _compute_created_count(self):
        for wizard in self:
            wizard.created_count = len(wizard.created_resource_ids)

    def _extract_filename_from_url(self, url):
        """Extract a filename from a URL, handling query parameters.

        Args:
            url (str): The URL to extract the filename from.

        Returns:
            str: The extracted filename or a default name if extraction fails.
        """
        parsed_url = urlparse(url)
        # Get the last part of the path
        filename = (
            os.path.basename(parsed_url.path)
            if parsed_url.path
            else "resource_from_url"
        )
        # Remove potential query parameters or fragments if they got stuck
        filename = re.sub(r"[?#].*", "", filename)
        # Basic sanitization (replace common problematic chars)
        filename = re.sub(r'[\\/:*?"<>|]', "_", filename)
        # Limit length
        return filename[:100] or "resource_from_url"  # Ensure not empty

    # ----------------------------------------------------
    # Private Helper Methods for Processing
    # ----------------------------------------------------
    def _process_file_uploads(self, collection):
        """Copy uploaded files into the collection's source backend and
        create native file resources for processing by a file extractor."""
        self.ensure_one()
        created_resources = self.env["llm.resource"]
        if not self.file_ids:
            return created_resources

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
            resource_name = self.resource_name_template.format(
                filename=filename,
                collection=collection.name,
                index=index + 1,
            )
            path = posixpath.join(upload_dir, f"{attachment.id}_{filename}")
            with backend.open(path, "wb") as stream:
                stream.write(base64.b64decode(attachment.datas or b""))
            created_resources |= self.env["llm.resource"].create(
                {
                    "name": resource_name,
                    "source_type": "file",
                    "source_backend_id": backend.id,
                    "source_path": path,
                    "collection_ids": [(4, collection.id)],
                }
            )
        return created_resources

    def _process_external_urls(self, collection, file_count):
        """Create URL resources for processing by an installed URL extractor."""
        self.ensure_one()
        created_resources = self.env["llm.resource"]
        urls = [
            url.strip()
            for url in (self.external_urls or "").splitlines()
            if url.strip()
        ]
        for index, url in enumerate(urls):
            filename = self._extract_filename_from_url(url)
            resource_name = self.resource_name_template.format(
                filename=filename,
                collection=collection.name,
                index=file_count + index + 1,
            )
            try:
                created_resources |= self.env["llm.resource"].create(
                    {
                        "name": resource_name,
                        "source_type": "url",
                        "source_url": url,
                        "collection_ids": [(4, collection.id)],
                    }
                )
            except Exception:  # noqa: BLE001
                _logger.exception("Failed to create llm.resource for URL %s", url)

        return created_resources

    # ----------------------------------------------------
    # Main Action
    # ----------------------------------------------------
    def action_upload_resources(self):
        """Create native file/URL resources and optionally process them."""
        self.ensure_one()
        collection = self.collection_id

        if not self.file_ids and not self.external_urls:
            raise UserError(_("Please provide at least one file or URL"))

        file_resources = self._process_file_uploads(collection)
        url_resources = self._process_external_urls(collection, len(self.file_ids))

        created_resources = file_resources | url_resources

        # Process resources if requested (full RAG pipeline)
        if self.process_immediately and created_resources:
            _logger.info(f"Processing {len(created_resources)} resources immediately.")
            for resource in created_resources:
                try:
                    resource.process_resource()  # Calls retriever, parser, embedder
                except Exception as e:
                    _logger.error(
                        f"Error processing resource {resource.id} ({resource.name}): {e}",
                        exc_info=True,
                    )
                    resource._post_styled_message(
                        f"Processing failed: {str(e)}", "error"
                    )

        # Update wizard state
        self.write(
            {
                "state": "done",
                "created_resource_ids": [(6, 0, created_resources.ids)],
            }
        )

        # Return action to show results or stay in wizard
        return {
            "type": "ir.actions.act_window",
            "res_model": self._name,
            "res_id": self.id,
            "view_mode": "form",
            "target": "new",
            "context": self.env.context,
        }

    # Method renamed for clarity
    def action_view_resources(self):
        """Open the created resources"""
        return {
            "name": "Uploaded RAG Resources",
            "type": "ir.actions.act_window",
            "res_model": "llm.resource",  # Target llm.resource
            "view_mode": "list,form,kanban",
            "domain": [
                ("id", "in", self.created_resource_ids.ids)
            ],  # Use renamed field
            # Use the specific views defined in llm_knowledge for llm.resource
            "view_ids": [
                (5, 0, 0),
                (
                    0,
                    0,
                    {
                        "view_mode": "kanban",
                        "view_id": self.env.ref(
                            "llm_knowledge.view_llm_resource_kanban"
                        ).id,
                    },
                ),
                (
                    0,
                    0,
                    {
                        "view_mode": "list",
                        "view_id": self.env.ref(
                            "llm_knowledge.view_llm_resource_tree"
                        ).id,
                    },
                ),
                (
                    0,
                    0,
                    {
                        "view_mode": "form",
                        "view_id": self.env.ref(
                            "llm_knowledge.view_llm_resource_form"
                        ).id,
                    },
                ),
            ],
            "search_view_id": [
                self.env.ref("llm_knowledge.view_llm_resource_search").id
            ],
        }
