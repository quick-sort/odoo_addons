import logging

from odoo import _, api, fields, models
from odoo.tools.safe_eval import safe_eval

_logger = logging.getLogger(__name__)


class LLMKnowledgeCollection(models.Model):
    """A knowledge base: a group of resources plus a shared markdown
    storage backend.

    This addon (llm_knowledge) only manages the knowledge collection, its
    resources, and the plain text/markdown extracted from those resources.
    Chunking and vector search are separate concerns owned by the llm_store
    addon (llm.knowledge.splitter/chunkset/vector, llm.store.chunk), which
    extends this model with chunkset_ids/vector_ids/embedding_model_id/
    store_id when installed.
    """

    _name = "llm.knowledge.collection"
    _description = "Knowledge Collection for RAG"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "name"

    name = fields.Char(
        string="Name",
        required=True,
        tracking=True,
    )
    description = fields.Text(
        string="Description",
        tracking=True,
    )
    active = fields.Boolean(
        string="Active",
        default=True,
        tracking=True,
    )
    md_backend_id = fields.Many2one(
        "storage.backend",
        string="Markdown Backend",
        tracking=True,
        help="Storage backend where resources' extracted markdown is kept "
        "as a managed artifact (e.g. filesystem, S3, SFTP/NAS). Optional: "
        "when unset, extracted markdown is only cached inline on the "
        "resource.",
    )
    source_backend_id = fields.Many2one(
        "storage.backend",
        string="Source Backend",
        ondelete="restrict",
        tracking=True,
        help="Storage backend holding the collection's original files. "
        "'Scan Storage' walks it (optionally limited to the Source Path) "
        "and creates a file resource per discovered file.",
    )
    source_path = fields.Char(
        string="Source Path",
        help="Optional subfolder inside the Source Backend to scan. Empty "
        "scans the backend root.",
    )
    resource_ids = fields.Many2many(
        "llm.resource",
        string="Resources",
        relation="llm_knowledge_resource_collection_rel",
        column1="collection_id",
        column2="resource_id",
    )
    # Domain filters for automatically adding resources
    domain_ids = fields.One2many(
        "llm.knowledge.domain",
        "collection_id",
        string="Domain Filters",
        help="Domain filters to select records for RAG document creation",
    )
    resource_count = fields.Integer(
        string="Resource Count",
        compute="_compute_resource_count",
    )
    default_parser = fields.Selection(
        selection=[
            ("default", "Default Parser"),
            ("json", "JSON Parser"),
        ],
        string="Default Parser",
        default="default",
        required=True,
        help="Default parser to use for record-type resources in this collection",
        tracking=True,
    )

    @api.depends("resource_ids")
    def _compute_resource_count(self):
        for record in self:
            record.resource_count = len(record.resource_ids)

    def _handle_resource_ids_change(self, old_resources_by_collection):
        for collection in self:
            old_resource_ids = old_resources_by_collection.get(collection.id, [])
            current_resource_ids = collection.resource_ids.ids
            removed_resource_ids = [
                rid for rid in old_resource_ids if rid not in current_resource_ids
            ]
            collection._handle_removed_resources(removed_resource_ids)
        return True

    def write(self, vals):
        collections_resources = {}
        if "resource_ids" in vals:
            for collection in self:
                collections_resources[collection.id] = collection.resource_ids.ids

        result = super().write(vals)

        if "resource_ids" in vals:
            self._handle_resource_ids_change(collections_resources)

        return result

    def action_view_resources(self):
        self.ensure_one()
        return {
            "name": _("Collection Resources"),
            "view_mode": "list,form",
            "res_model": "llm.resource",
            "domain": [("id", "in", self.resource_ids.ids)],
            "type": "ir.actions.act_window",
            "context": {"default_collection_ids": [(6, 0, [self.id])]},
        }

    def sync_resources(self):
        """
        Synchronize collection resources with domain filters.
        This will:
        1. Add new resources for records matching domain filters
        2. Remove resources that no longer match domain filters
        """
        for collection in self:
            if not collection.domain_ids:
                continue

            created_count = 0
            linked_count = 0
            removed_count = 0

            matching_records = []
            model_map = {}

            for domain_filter in collection.domain_ids.filtered(lambda d: d.active):
                model_name = domain_filter.model_name
                if model_name not in self.env:
                    collection._post_styled_message(
                        _(f"Model '{model_name}' not found. Skipping."),
                        message_type="warning",
                    )
                    continue

                model = self.env[model_name]
                domain = safe_eval(domain_filter.domain)
                records = model.search(domain)

                if not records:
                    collection._post_styled_message(
                        _(
                            f"No records found for model '{domain_filter.model_id.name}' with given domain."
                        ),
                        message_type="info",
                    )
                    continue

                for record in records:
                    matching_records.append((model_name, record.id))
                    model_map[(model_name, record.id)] = domain_filter.model_id

            existing_docs = collection.resource_ids
            docs_to_keep = self.env["llm.resource"]

            for model_name, record_id in matching_records:
                record = self.env[model_name].browse(record_id)
                model_id = model_map[(model_name, record_id)].id

                existing_doc = self.env["llm.resource"].search(
                    [
                        ("model_id", "=", model_id),
                        ("res_id", "=", record_id),
                    ],
                    limit=1,
                )

                if existing_doc:
                    if existing_doc in existing_docs:
                        docs_to_keep |= existing_doc
                    elif existing_doc.id not in collection.resource_ids.ids:
                        collection.write({"resource_ids": [(4, existing_doc.id)]})
                        linked_count += 1
                        docs_to_keep |= existing_doc
                else:
                    if hasattr(record, "display_name") and record.display_name:
                        name = record.display_name
                    elif hasattr(record, "name") and record.name:
                        name = record.name
                    else:
                        model_display = self.env["ir.model"]._get(model_name).name
                        name = f"{model_display} #{record_id}"

                    new_doc = self.env["llm.resource"].create(
                        {
                            "name": name,
                            "source_type": "record",
                            "model_id": model_id,
                            "res_id": record_id,
                            "parser": "json",
                            "collection_ids": [(4, collection.id)],
                        }
                    )
                    docs_to_keep |= new_doc
                    created_count += 1

            docs_to_remove = existing_docs - docs_to_keep

            if docs_to_remove:
                collection.write(
                    {"resource_ids": [(3, doc.id) for doc in docs_to_remove]}
                )
                removed_count = len(docs_to_remove)

            if created_count > 0 or linked_count > 0 or removed_count > 0:
                collection._post_styled_message(
                    _(
                        f"Synchronization complete: Created {created_count} new resources, "
                        f"linked {linked_count} existing resources, "
                        f"removed {removed_count} resources no longer matching domains."
                    ),
                    message_type="success",
                )
            else:
                collection._post_styled_message(
                    _("No changes made - collection is already in sync with domains."),
                    message_type="info",
                )

    def process_resources(self):
        """Process resources through retrieval and parsing (up to parsed state)"""
        for collection in self:
            collection.resource_ids.process_resource()

    def action_open_upload_wizard(self):
        self.ensure_one()
        return {
            "name": "Upload Resources",
            "type": "ir.actions.act_window",
            "res_model": "llm.upload.resource.wizard",
            "view_mode": "form",
            "target": "new",
            "context": {
                "default_collection_id": self.id,
                "default_resource_name_template": "{filename}",
            },
        }

    # ------------------------------------------------------------------
    # Extension points for llm_store (and other addons) to hook resource
    # removal cleanup without llm_knowledge knowing about vectors/chunks.
    # ------------------------------------------------------------------
    def _handle_removed_resources(self, removed_resource_ids):
        self.ensure_one()
        if removed_resource_ids:
            _logger.info(
                f"Resources {removed_resource_ids} were removed from collection {self.id}"
            )
            resources = self.env["llm.resource"].browse(removed_resource_ids)
            for resource in resources:
                resource._reset_state_if_needed()
        return True
