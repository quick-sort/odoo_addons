import logging
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import UserError

_logger = logging.getLogger(__name__)


class LLMResource(models.Model):
    """A document/record wrapper managed by a knowledge collection.

    llm_knowledge owns retrieval and parsing only: a resource's own
    lifecycle here ends at 'parsed' (plain text/markdown available, either
    cached inline in `content` or as a managed artifact on the owning
    collection's md_backend_id). Chunking, embedding and vector search are
    separate concerns owned by the llm_store addon, which extends this
    model with `chunk_ids`/`state` selection_add ('chunked', 'ready') and
    the corresponding actions when installed.
    """

    _name = "llm.resource"
    _description = "LLM Resource for Document Management"
    _inherit = ["mail.thread", "mail.activity.mixin"]
    _order = "id desc"

    _unique_resource_reference = models.Constraint(
        "UNIQUE(model_id, res_id)",
        "A resource already exists for this record. Please use the existing resource.",
    )

    name = fields.Char(
        string="Name",
        required=True,
        tracking=True,
    )
    model_id = fields.Many2one(
        "ir.model",
        string="Related Model",
        tracking=True,
        ondelete="cascade",
        help="The model of the referenced document. Only used for "
        "source_type='record'.",
    )
    res_model = fields.Char(
        string="Model Name",
        related="model_id.model",
        store=True,
        readonly=True,
        help="Technical name of the related model",
    )
    res_id = fields.Integer(
        string="Record ID",
        tracking=True,
        help="The ID of the referenced record. Only used for "
        "source_type='record'.",
    )
    source_type = fields.Selection(
        selection=[
            ("record", "Odoo Record"),
            ("file", "File"),
            ("url", "URL"),
        ],
        string="Source Type",
        default="record",
        required=True,
        tracking=True,
        help="Where this resource's raw content comes from. 'Odoo Record' "
        "keeps the existing polymorphic model_id/res_id behavior; 'File' "
        "reads from a one.storage.entry; 'URL' fetches a remote page.",
    )
    entry_id = fields.Many2one(
        "one.storage.entry",
        string="Storage Entry",
        ondelete="restrict",
        index=True,
        help="Source file for 'File' type resources.",
    )
    source_url = fields.Char(
        string="Source URL",
        help="Source URL for 'URL' type resources.",
    )
    content_path = fields.Char(
        string="Markdown Path",
        compute="_compute_content_path",
        help="Path of the extracted markdown inside the collection's "
        "markdown backend (collection_id.md_backend_id).",
    )
    content = fields.Text(
        string="Content",
        help="Markdown representation of the resource content. Cached "
        "in-database copy; the managed artifact lives on the collection's "
        "md_backend_id at content_path when one is configured.",
    )
    external_url = fields.Char(
        string="External URL",
        compute="_compute_external_url",
        store=True,
        help="External URL from the related record if available",
    )
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("retrieved", "Retrieved"),
            ("parsed", "Parsed"),
        ],
        string="State",
        default="draft",
        tracking=True,
    )
    lock_date = fields.Datetime(
        string="Lock Date",
        tracking=True,
        help="Date when the resource was locked for processing",
    )
    kanban_state = fields.Selection(
        [
            ("normal", "Ready"),
            ("blocked", "Blocked"),
            ("done", "Done"),
        ],
        string="Kanban State",
        compute="_compute_kanban_state",
        store=True,
    )

    collection_ids = fields.Many2many(
        "llm.knowledge.collection",
        relation="llm_knowledge_resource_collection_rel",
        column1="resource_id",
        column2="collection_id",
        string="Collections",
    )

    @api.depends("res_model", "res_id")
    def _compute_external_url(self):
        for resource in self:
            resource.external_url = False
            if not resource.res_model or not resource.res_id:
                continue

            resource.external_url = self._get_record_external_url(
                resource.res_model, resource.res_id
            )

    @api.depends("collection_ids.md_backend_id")
    def _compute_content_path(self):
        for resource in self:
            resource.content_path = (
                "%s/content.md" % resource.id if resource.id else False
            )

    @api.constrains("source_type", "model_id", "res_id", "entry_id", "source_url")
    def _check_source_reference(self):
        for resource in self:
            if resource.source_type == "record" and (
                not resource.model_id or not resource.res_id
            ):
                raise UserError(
                    _(
                        "Resource '%s': a record-type resource requires a "
                        "related model and record ID.",
                        resource.name,
                    )
                )
            if resource.source_type == "file" and not resource.entry_id:
                raise UserError(
                    _(
                        "Resource '%s': a file-type resource requires a "
                        "storage entry.",
                        resource.name,
                    )
                )
            if resource.source_type == "url" and not resource.source_url:
                raise UserError(
                    _("Resource '%s': a URL-type resource requires a URL.", resource.name)
                )

    def _get_md_backend(self):
        """Storage backend used for this resource's extracted markdown,
        taken from the first collection that has one configured."""
        self.ensure_one()
        for collection in self.collection_ids:
            if collection.md_backend_id:
                return collection.md_backend_id
        return None

    def _read_source_bytes(self):
        """Return the raw bytes of a file-type resource's source file."""
        self.ensure_one()
        if self.source_type != "file" or not self.entry_id:
            return None
        return self.entry_id.read_bytes()

    def _write_content_to_backend(self, markdown_text):
        """Persist extracted markdown to the collection's md_backend_id
        (if configured) at content_path, and keep an inline cached copy."""
        self.ensure_one()
        self.content = markdown_text
        backend = self._get_md_backend()
        if backend and self.content_path:
            data = (markdown_text or "").encode("utf-8")
            with backend.open(self.content_path, "wb") as stream:
                stream.write(data)

    def _read_content_from_backend(self):
        """Read extracted markdown back from the collection's md_backend_id
        if configured, falling back to the cached inline content field."""
        self.ensure_one()
        backend = self._get_md_backend()
        if backend and self.content_path and backend.file_exists(self.content_path):
            with backend.open(self.content_path, "rb") as stream:
                return stream.read().decode("utf-8")
        return self.content or ""

    def _get_record_external_url(self, res_model, res_id):
        """
        Get the external URL for a record based on its model and ID.

        This method can be extended by other modules to support additional models.

        :param res_model: The model name
        :param res_id: The record ID
        :return: The external URL or False
        """
        try:
            # Get the related record
            if res_model in self.env:
                record = self.env[res_model].browse(res_id)
                if not record.exists():
                    return False

                # Case 1: Handle ir.attachment with type 'url'
                if res_model == "ir.attachment" and hasattr(record, "type"):
                    if record.type == "url" and hasattr(record, "url"):
                        return record.url

                # Case 2: Check if record has an external_url field
                elif hasattr(record, "external_url"):
                    return record.external_url

        except Exception as e:
            _logger.warning(
                "Error computing external URL for resource model %s, id %s: %s",
                res_model,
                res_id,
                str(e),
            )

        return False

    @api.depends("lock_date")
    def _compute_kanban_state(self):
        for record in self:
            record.kanban_state = "blocked" if record.lock_date else "normal"

    def _lock(self, state_filter=None, stale_lock_minutes=10):
        """Lock resources for processing and return the ones successfully locked"""
        now = fields.Datetime.now()
        stale_lock_threshold = now - timedelta(minutes=stale_lock_minutes)

        # Find resources that are not locked or have stale locks
        domain = [
            ("id", "in", self.ids),
            "|",
            ("lock_date", "=", False),
            ("lock_date", "<", stale_lock_threshold),
        ]
        if state_filter:
            domain.append(("state", "=", state_filter))

        unlocked_docs = self.env["llm.resource"].search(domain)

        if unlocked_docs:
            unlocked_docs.write({"lock_date": now})

        return unlocked_docs

    def _unlock(self):
        """Unlock resources after processing"""
        return self.write({"lock_date": False})

    def process_resource(self):
        """
        Process resources through retrieval and parsing.
        Can handle multiple resources at once, processing them through
        as many pipeline stages as possible based on their current states.

        llm_store extends this (via _inherit) to continue the pipeline into
        chunking/embedding once a resource reaches 'parsed'.
        """
        # Stage 1: Retrieve content for draft resources
        draft_docs = self.filtered(lambda d: d.state == "draft")
        if draft_docs:
            draft_docs.retrieve()

        # Stage 2: Parse retrieved resources
        retrieved_docs = self.filtered(lambda d: d.state == "retrieved")
        if retrieved_docs:
            retrieved_docs.parse()

        return True

    def action_open_resource(self):
        """Open the resource in form view."""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "res_model": "llm.resource",
            "res_id": self.id,
            "view_mode": "form",
            "target": "current",
        }

    @api.model
    def action_mass_process_resources(self):
        """
        Server action handler for mass processing resources.
        This will be triggered from the server action in the UI.
        """
        active_ids = self.env.context.get("active_ids", [])
        if not active_ids:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("No Resources Selected"),
                    "message": _("Please select resources to process."),
                    "type": "warning",
                    "sticky": False,
                },
            }

        resources = self.browse(active_ids)
        # Process all selected resources
        result = resources.process_resource()

        if result:
            return {
                "type": "ir.actions.client",
                "tag": "reload",
            }

        else:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("Processing Failed"),
                    "message": _("Mass processing resources failed"),
                    "sticky": False,
                    "type": "danger",
                },
            }

    def action_mass_unlock(self):
        """
        Mass unlock action for the server action.
        """
        # Unlock the resources
        self._unlock()

        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Resources Unlocked"),
                "message": _("%(count)s resources have been unlocked", count=len(self)),
                "sticky": False,
                "type": "success",
            },
        }

    def action_mass_reset(self):
        """
        Mass reset action for the server action.
        Resets all non-draft resources back to draft state.
        """
        # Get active IDs from context
        active_ids = self.env.context.get("active_ids", [])
        if not active_ids:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("No Resources Selected"),
                    "message": _("Please select resources to reset."),
                    "type": "warning",
                    "sticky": False,
                },
            }

        resources = self.browse(active_ids)
        # Filter resources that are not in draft state
        non_draft_resources = resources.filtered(lambda r: r.state != "draft")

        if not non_draft_resources:
            return {
                "type": "ir.actions.client",
                "tag": "display_notification",
                "params": {
                    "title": _("No Resources Reset"),
                    "message": _("No resources found that need resetting."),
                    "type": "warning",
                    "sticky": False,
                },
            }

        # Reset resources to draft state and unlock them
        non_draft_resources.write(
            {
                "state": "draft",
                "lock_date": False,
            }
        )

        # Reload the view to reflect changes
        return {
            "type": "ir.actions.client",
            "tag": "reload",
            "params": {
                "menu_id": self.env.context.get("menu_id"),
                "action": self.env.context.get("action"),
            },
        }

    def _reset_state_if_needed(self):
        """Hook called when a resource is removed from all collections.
        Base implementation is a no-op; llm_store extends this to reset
        'ready' resources back to 'chunked' for re-embedding."""
        self.ensure_one()
        return True

    def _handle_collection_ids_change(self, old_collections_by_resource):
        """Handle changes to collection_ids field.

        Args:
            old_collections_by_resource: Dictionary mapping resource IDs to their previous collection IDs
        """
        for resource in self:
            old_collection_ids = old_collections_by_resource.get(resource.id, [])
            current_collection_ids = resource.collection_ids.ids

            # Find collections that the resource was removed from
            removed_collection_ids = [
                cid for cid in old_collection_ids if cid not in current_collection_ids
            ]

            # Notify collections so they (or extending addons) can clean up
            if removed_collection_ids:
                collections = self.env["llm.knowledge.collection"].browse(
                    removed_collection_ids
                )
                for collection in collections:
                    collection._handle_removed_resources([resource.id])

        return True

    def write(self, vals):
        """Override write to notify collections of collection_ids changes"""
        # Track collections before the write
        resources_collections = {}
        if "collection_ids" in vals:
            for resource in self:
                resources_collections[resource.id] = resource.collection_ids.ids

        # Perform the write operation
        result = super().write(vals)

        # Handle collection changes
        if "collection_ids" in vals:
            self._handle_collection_ids_change(resources_collections)

        return result
