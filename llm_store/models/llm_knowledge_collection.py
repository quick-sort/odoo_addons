"""Extends llm.knowledge.collection (from llm_knowledge) with chunking and
vector-store configuration.

llm_knowledge only knows about resources and their plain text/markdown; a
collection does not carry a single store/embedding-model pair by itself.
This addon adds ``chunkset_ids`` (N chunking configurations per collection)
and, through them, ``vector_ids`` (N embedding-model x vector-store
configurations per chunkset) -- so one knowledge base can be indexed with
several chunk sizes and compared across several vector stores (e.g.
pgvector vs. qdrant) at once.

``embedding_model_id``/``store_id`` below are convenience fields for the
common single-configuration case: writing them transparently creates/
updates a "Default" chunkset+vector pair, so simple setups keep the same
one-field-each experience while power users add more chunksets/vectors for
comparison.
"""

import logging

from odoo import _, api, fields, models

from .llm_resource_chunker import DEFAULT_CHUNK_OVERLAP, DEFAULT_CHUNK_SIZE

_logger = logging.getLogger(__name__)

_DEFAULT_CHUNKSET_NAME = "Default"


class LLMKnowledgeCollection(models.Model):
    _inherit = "llm.knowledge.collection"

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
    chunk_count = fields.Integer(
        string="Chunk Count",
        compute="_compute_chunk_count",
    )
    chunk_ids = fields.Many2many(
        "llm.store.chunk",
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
        selection=[
            ("recursive", "Recursive"),
            ("token", "Token"),
            ("contextual", "Contextual"),
        ],
        string="Default Splitter",
        default="recursive",
        required=True,
        help="Splitter type for this collection's default chunkset "
        "('contextual' enables contextual-retrieval wrapping).",
        tracking=True,
    )

    @api.depends("resource_ids.chunk_ids")
    def _compute_chunk_ids(self):
        for collection in self:
            collection.chunk_ids = collection.resource_ids.mapped("chunk_ids")

    @api.depends("chunk_ids")
    def _compute_chunk_count(self):
        for collection in self:
            collection.chunk_count = len(collection.chunk_ids)

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

    @api.depends(
        "chunkset_ids.vector_ids.is_default",
        "chunkset_ids.vector_ids.embedding_model_id",
        "chunkset_ids.vector_ids.store_id",
    )
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

    def _sync_default_chunkset_vector(self, embedding_model_id=None, store_id=None):
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

        result = super().write(vals)

        if needs_chunking_sync:
            for collection in self:
                collection._sync_default_chunkset_vector(
                    embedding_model_id=collection.embedding_model_id.id,
                    store_id=collection.store_id.id,
                )

        return result

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

    def action_view_chunks(self):
        self.ensure_one()
        return {
            "name": _("Collection Chunks"),
            "view_mode": "list,form",
            "res_model": "llm.store.chunk",
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

    def _handle_removed_resources(self, removed_resource_ids):
        """Extend the base hook: also remove this resource's vectors/chunks
        from every vector configuration of this collection."""
        result = super()._handle_removed_resources(removed_resource_ids)
        if removed_resource_ids:
            resources = self.env["llm.resource"].browse(removed_resource_ids)
            for resource in resources:
                self._handle_resource_removal(resource)
        return result

    def _handle_resource_removal(self, resource):
        """Remove this resource's chunks/vectors from every vector
        configuration of this collection."""
        self.ensure_one()
        for vector in self.vector_ids:
            if not vector.store_id or not vector.store_id.collection_exists(vector.id):
                continue
            chunks = self.env["llm.store.chunk"].search(
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
