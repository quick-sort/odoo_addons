import logging

from odoo import _, api, fields, models
from odoo.tools.safe_eval import safe_eval

from .llm_resource_chunker import DEFAULT_CHUNK_OVERLAP, DEFAULT_CHUNK_SIZE

_logger = logging.getLogger(__name__)

_DEFAULT_CHUNKSET_NAME = "Default"


class LLMKnowledgeCollection(models.Model):
    """A knowledge base: a group of resources plus one or more chunking/
    vectorization configurations.

    Unlike the previous design, a collection does NOT itself carry a single
    ``store_id``/``embedding_model_id`` pair anymore -- it can hold several
    ``llm.knowledge.chunkset`` (different splitters/chunk sizes) each
    feeding several ``llm.knowledge.vector`` (different embedding
    models/dimensions/stores). ``embedding_model_id``/``store_id`` below are
    kept as convenience fields for the common single-configuration case:
    writing them transparently creates/updates a "Default" chunkset+vector
    pair, so simple setups keep the same one-field-each experience while
    power users can add more chunksets/vectors for comparison.
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
    embedding_model_id = fields.Many2one(
        "llm.model",
        string="Embedding Model",
        compute="_compute_default_vector_fields",
        inverse="_inverse_embedding_model_id",
        store=True,
        readonly=False,
        domain="[('model_use', '=', 'embedding')]",
        tracking=True,
        help="Convenience field: mirrors the embedding model of this "
        "collection's default vector configuration. For multiple embedding "
        "models per collection, add more llm.knowledge.vector records "
        "instead.",
    )
    store_id = fields.Many2one(
        "llm.store",
        string="Vector Store",
        compute="_compute_default_vector_fields",
        inverse="_inverse_store_id",
        store=True,
        readonly=False,
        tracking=True,
        help="Convenience field: mirrors the vector store of this "
        "collection's default vector configuration. For multiple vector "
        "stores per collection, add more llm.knowledge.vector records "
        "instead.",
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
    chunk_count = fields.Integer(
        string="Chunk Count",
        compute="_compute_chunk_count",
    )
    chunk_ids = fields.Many2many(
        "llm.knowledge.chunk",
        string="Chunks (from Resources)",
        compute="_compute_chunk_ids",
        store=False,
        help="Chunks belonging to the resources included in this collection.",
    )
    chunkset_ids = fields.One2many(
        "llm.knowledge.chunkset",
        "collection_id",
        string="Chunking Configurations",
        help="A collection can hold several chunksets (different "
        "splitters/chunk sizes, including 'contextual' for "
        "contextual-retrieval wrapping); each chunkset can in turn feed "
        "several llm.knowledge.vector configurations (different embedding "
        "models/dimensions/stores).",
    )
    chunkset_count = fields.Integer(compute="_compute_chunkset_count")
    vector_ids = fields.Many2many(
        "llm.knowledge.vector",
        string="Vector Configurations",
        compute="_compute_vector_ids",
        store=False,
    )
    vector_count = fields.Integer(compute="_compute_vector_count")

    # Default chunking settings, used to seed the "Default" chunkset/vector
    # convenience pair (see embedding_model_id/store_id docstring above).
    default_chunk_size = fields.Integer(
        string="Default Chunk Size",
        default=DEFAULT_CHUNK_SIZE,
        required=True,
        help="Chunk size (characters) for this collection's default chunkset.",
        tracking=True,
    )
    default_chunk_overlap = fields.Integer(
        string="Default Chunk Overlap",
        default=DEFAULT_CHUNK_OVERLAP,
        required=True,
        help="Chunk overlap (characters) for this collection's default chunkset.",
        tracking=True,
    )
    default_splitter_type = fields.Selection(
        selection="_get_available_splitters",
        string="Default Splitter",
        default="recursive",
        required=True,
        help="Splitter type for this collection's default chunkset "
        "('contextual' enables contextual-retrieval wrapping).",
        tracking=True,
    )
    default_parser = fields.Selection(
        selection="_get_available_parsers",
        string="Default Parser",
        default="default",
        required=True,
        help="Default parser to use for record-type resources in this collection",
        tracking=True,
    )

    @api.model
    def _get_available_parsers(self):
        return self.env["llm.resource"]._get_available_parsers()

    @api.model
    def _get_available_splitters(self):
        return self.env["llm.knowledge.splitter"]._selection_splitter_type()

    @api.depends("resource_ids.chunk_ids")
    def _compute_chunk_ids(self):
        for collection in self:
            collection.chunk_ids = collection.resource_ids.mapped("chunk_ids")

    @api.depends("chunkset_ids")
    def _compute_chunkset_count(self):
        for collection in self:
            collection.chunkset_count = len(collection.chunkset_ids)

    @api.depends("chunkset_ids.vector_ids")
    def _compute_vector_ids(self):
        for collection in self:
            collection.vector_ids = collection.chunkset_ids.mapped("vector_ids")

    @api.depends("vector_ids")
    def _compute_vector_count(self):
        for collection in self:
            collection.vector_count = len(collection.vector_ids)

    @api.depends("chunkset_ids.vector_ids.is_default", "chunkset_ids.vector_ids.embedding_model_id", "chunkset_ids.vector_ids.store_id")
    def _compute_default_vector_fields(self):
        for collection in self:
            vector = collection._get_default_vector()
            collection.embedding_model_id = vector.embedding_model_id if vector else False
            collection.store_id = vector.store_id if vector else False

    def _inverse_embedding_model_id(self):
        for collection in self:
            collection._sync_default_chunkset_vector(
                embedding_model_id=collection.embedding_model_id.id
            )

    def _inverse_store_id(self):
        for collection in self:
            collection._sync_default_chunkset_vector(store_id=collection.store_id.id)

    @api.depends("resource_ids")
    def _compute_resource_count(self):
        for record in self:
            record.resource_count = len(record.resource_ids)

    @api.depends("chunk_ids")
    def _compute_chunk_count(self):
        for record in self:
            record.chunk_count = len(record.chunk_ids)

    # ------------------------------------------------------------------
    # Default chunkset/vector management (backs the convenience fields)
    # ------------------------------------------------------------------
    def _get_default_chunkset(self):
        self.ensure_one()
        return self.chunkset_ids.filtered("is_default")[:1]

    def _get_default_vector(self):
        self.ensure_one()
        chunkset = self._get_default_chunkset()
        return chunkset.vector_ids.filtered("is_default")[:1] if chunkset else False

    def _sync_default_chunkset_vector(
        self, embedding_model_id=None, store_id=None
    ):
        """Create/update the "Default" chunkset+vector pair from this
        collection's embedding_model_id/store_id/default_* fields (or the
        explicit overrides passed in, used by the compute/inverse fields to
        avoid read-after-write ordering issues). A no-op if neither an
        embedding model nor a store is configured yet, and no chunkset
        exists already to update."""
        self.ensure_one()
        model_id = (
            embedding_model_id
            if embedding_model_id is not None
            else self.embedding_model_id.id
        )
        store = store_id if store_id is not None else self.store_id.id

        chunkset = self._get_default_chunkset()
        if not chunkset and not (model_id or store):
            # Nothing configured yet and no existing default to maintain:
            # skip creating an empty chunkset for collections that don't
            # embed anything directly (e.g. pure domain-sync containers).
            return False

        if not chunkset:
            splitter = self.env["llm.knowledge.splitter"].create(
                {
                    "name": _("%s - Default Splitter", self.name),
                    "splitter_type": self.default_splitter_type or "recursive",
                    "chunk_size": self.default_chunk_size,
                    "chunk_overlap": self.default_chunk_overlap,
                }
            )
            chunkset = self.env["llm.knowledge.chunkset"].create(
                {
                    "name": _DEFAULT_CHUNKSET_NAME,
                    "collection_id": self.id,
                    "splitter_id": splitter.id,
                    "is_default": True,
                }
            )
        else:
            chunkset.splitter_id.write(
                {
                    "splitter_type": self.default_splitter_type
                    or chunkset.splitter_id.splitter_type,
                    "chunk_size": self.default_chunk_size,
                    "chunk_overlap": self.default_chunk_overlap,
                }
            )

        vector = self._get_default_vector()
        if not vector and model_id and store:
            self.env["llm.knowledge.vector"].create(
                {
                    "name": _DEFAULT_CHUNKSET_NAME,
                    "chunkset_id": chunkset.id,
                    "embedding_model_id": model_id,
                    "store_id": store,
                    "is_default": True,
                }
            )
        elif vector:
            update_vals = {}
            if model_id and vector.embedding_model_id.id != model_id:
                update_vals["embedding_model_id"] = model_id
            if store and vector.store_id.id != store:
                update_vals["store_id"] = store
            if update_vals:
                vector.write(update_vals)
                self._reset_ready_resources(
                    success_message=_(
                        "Default vector configuration changed. Reset {count} "
                        "resources for re-embedding."
                    )
                )
        return True

    def write(self, vals):
        chunking_fields = {
            "default_chunk_size",
            "default_chunk_overlap",
            "default_splitter_type",
        }
        needs_chunking_sync = bool(chunking_fields & set(vals))

        collections_resources = {}
        if "resource_ids" in vals:
            for collection in self:
                collections_resources[collection.id] = collection.resource_ids.ids

        result = super().write(vals)

        if needs_chunking_sync:
            for collection in self:
                collection._sync_default_chunkset_vector(
                    embedding_model_id=collection.embedding_model_id.id,
                    store_id=collection.store_id.id,
                )

        if "resource_ids" in vals:
            self._handle_resource_ids_change(collections_resources)

        return result

    def _handle_resource_ids_change(self, old_resources_by_collection):
        for collection in self:
            old_resource_ids = old_resources_by_collection.get(collection.id, [])
            current_resource_ids = collection.resource_ids.ids
            removed_resource_ids = [
                rid for rid in old_resource_ids if rid not in current_resource_ids
            ]
            collection._handle_removed_resources(removed_resource_ids)
        return True

    def unlink(self):
        # llm.knowledge.chunkset/vector are cascade-deleted by the ORM
        # (ondelete=cascade), which also runs llm.knowledge.vector.unlink()
        # to clean up their store-side collections.
        return super().unlink()

    def _reset_ready_resources(
        self, success_message="Reset {{count}} resources for re-embedding."
    ):
        """Finds ready resources, resets their state to 'chunked', and posts a message."""
        self.ensure_one()
        ready_resources = self.resource_ids.filtered(lambda r: r.state == "ready")
        if ready_resources:
            count = len(ready_resources)
            ready_resources.write({"state": "chunked"})
            self._post_styled_message(
                success_message.format(count=count), message_type="info"
            )
            return count
        return 0

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

    def action_view_chunks(self):
        self.ensure_one()
        return {
            "name": _("Collection Chunks"),
            "view_mode": "list,form",
            "res_model": "llm.knowledge.chunk",
            "domain": [("collection_ids", "=", self.id)],
            "type": "ir.actions.act_window",
        }

    def action_view_chunksets(self):
        self.ensure_one()
        return {
            "name": _("Chunking Configurations"),
            "view_mode": "list,form",
            "res_model": "llm.knowledge.chunkset",
            "domain": [("collection_id", "=", self.id)],
            "type": "ir.actions.act_window",
            "context": {"default_collection_id": self.id},
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
        """Process resources through retrieval, parsing, and chunking (up to chunked state)"""
        for collection in self:
            collection.resource_ids.process_resource()

    def reindex_collection(self):
        """Reindex every vector configuration of this collection: drop and
        rebuild each vector's store-side collection, resetting resources
        for re-embedding."""
        for collection in self:
            if not collection.vector_ids:
                reset_count = collection._reset_ready_resources(
                    success_message=_("Reset {count} resources for re-embedding.")
                )
                if not reset_count:
                    collection._post_styled_message(
                        _("No resources found to reindex."), message_type="info"
                    )
                continue

            for vector in collection.vector_ids:
                try:
                    vector.action_drop()
                    vector._initialize_store()
                except Exception as e:  # noqa: BLE001
                    collection._post_styled_message(
                        _("Error reindexing vector '%s': %s", vector.name, str(e)),
                        message_type="error",
                    )

            reset_count = collection._reset_ready_resources(
                success_message=_(
                    "Reset {count} resources for re-embedding across "
                    f"{len(collection.vector_ids)} vector configuration(s)."
                )
            )
            if not reset_count:
                collection._post_styled_message(
                    _("No resources found to reindex."), message_type="info"
                )

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

    def action_embed_resources(self, specific_resource_ids=None):
        """Action handler for embedding resources in the UI."""
        self.ensure_one()
        result = self.embed_resources(specific_resource_ids=specific_resource_ids)

        if result and result.get("success"):
            return True
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Embedding Failed"),
                "message": _("Failed to embed resources. Check the logs for details."),
                "type": "warning",
                "sticky": False,
            },
        }

    def embed_resources(self, specific_resource_ids=None, batch_size=50):
        """Build every vector configuration of this collection for its
        resources (chunked resources only). Each vector splits, embeds and
        upserts independently -- see llm.knowledge.vector.action_build.
        ``batch_size`` is currently informational only: vectors batch per
        resource, not per fixed chunk count, since chunking is transient."""
        overall_success = False
        processed_chunks_total = 0
        processed_resources = set()

        for collection in self:
            if not collection.vector_ids:
                collection._post_styled_message(
                    _(
                        "No vector configuration found for this collection. "
                        "Set an embedding model and vector store, or add an "
                        "llm.knowledge.vector record."
                    ),
                    message_type="warning",
                )
                continue

            resources = collection.resource_ids
            if specific_resource_ids:
                resources = resources.filtered(lambda r: r.id in specific_resource_ids)
            resources = resources.filtered(lambda r: r.state in ("chunked", "ready"))

            if not resources:
                collection._post_styled_message(
                    _("No chunked resources found to embed."), message_type="info"
                )
                continue

            for vector in collection.vector_ids:
                try:
                    vector.action_build(specific_resource_ids=resources.ids)
                    overall_success = True
                    processed_resources.update(resources.ids)
                    processed_chunks_total += len(vector.chunkset_id.chunk_ids)
                except Exception as e:  # noqa: BLE001
                    collection._post_styled_message(
                        _(
                            "Error building vector '%s': %s",
                            vector.name,
                            str(e),
                        ),
                        message_type="error",
                    )

            if overall_success:
                resources.write({"state": "ready"})
                self.env.cr.commit()
                collection._post_styled_message(
                    _(
                        "Successfully embedded %d resources across %d vector "
                        "configuration(s).",
                        len(resources),
                        len(collection.vector_ids),
                    ),
                    message_type="success",
                )

        return {
            "success": overall_success,
            "processed_chunks": processed_chunks_total,
            "processed_resources": len(processed_resources),
        }

    # Helper method for resource-collection relationship changes
    def _handle_removed_resources(self, removed_resource_ids):
        self.ensure_one()
        if removed_resource_ids:
            _logger.info(
                f"Resources {removed_resource_ids} were removed from collection {self.id}"
            )
            resources = self.env["llm.resource"].browse(removed_resource_ids)
            for resource in resources:
                self._handle_resource_removal(resource)
                resource._reset_state_if_needed()
        return True

    def _handle_resource_removal(self, resource):
        """Remove this resource's chunks/vectors from every vector
        configuration of this collection."""
        self.ensure_one()
        for vector in self.vector_ids:
            if not vector.store_id or not vector.store_id.collection_exists(vector.id):
                continue
            chunks = self.env["llm.knowledge.chunk"].search(
                [
                    ("chunkset_id", "=", vector.chunkset_id.id),
                    ("resource_id", "=", resource.id),
                ]
            )
            if not chunks:
                continue
            try:
                vector.delete_vectors(ids=chunks.ids)
                chunks.unlink()
                _logger.info(
                    f"Removed vectors/chunks for resource {resource.id} from vector {vector.id}"
                )
            except Exception as e:  # noqa: BLE001
                _logger.warning(
                    f"Error removing vectors for resource {resource.id} from vector {vector.id}: {str(e)}"
                )
        return True
