"""One logical vector database hosted by a store instance.

A knowledge chunkset may be indexed into several databases for retrieval
benchmarking. Each database owns one fixed dense/sparse model combination,
dense dimension, query interfaces, isolation/tenant settings, an offline
maintenance lifecycle, and provider-record mappings.
"""

import hashlib
import json
import logging
import uuid as uuid_lib

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError

_logger = logging.getLogger(__name__)


class LLMStoreDatabase(models.Model):
    _name = "llm.store.database"
    _description = "LLM Store Database"
    _inherit = ["llm.store.collection"]
    _order = "store_id, name, id"

    knowledge_collection_id = fields.Many2one(
        "llm.knowledge.collection",
        string="Knowledge Collection",
        required=True,
        ondelete="restrict",
        index=True,
        tracking=True,
        help="The single logical knowledge collection stored in this database.",
    )
    chunkset_id = fields.Many2one(
        "llm.knowledge.chunkset",
        string="Chunking Configuration",
        required=True,
        ondelete="restrict",
        index=True,
        tracking=True,
        domain="[('collection_id', '=', knowledge_collection_id)]",
        help="The splitting method used to build this database.",
    )
    dense_embedding_model_id = fields.Many2one(
        "llm.model",
        string="Dense Embedding Model",
        ondelete="restrict",
        tracking=True,
        domain="[('model_use', '=', 'embedding'), ('embedding_type', '=', 'dense')]",
        help="Model producing fixed-dimension dense vectors for this database.",
    )
    sparse_embedding_model_id = fields.Many2one(
        "llm.model",
        string="Sparse Embedding Model",
        ondelete="restrict",
        tracking=True,
        domain="[('model_use', '=', 'embedding'), ('embedding_type', '=', 'sparse')]",
        help="Model producing weighted sparse vectors for this database.",
    )

    # Stable identities separate Odoo rows, logical retrieval records, and
    # provider-side point/row/document IDs.
    uuid = fields.Char(
        required=True,
        default=lambda self: str(uuid_lib.uuid4()),
        copy=False,
        readonly=True,
        index=True,
    )
    backend_key = fields.Char(
        copy=False,
        readonly=True,
        index=True,
        help="Immutable Odoo-owned scope identity passed to provider adapters.",
    )
    database_name = fields.Char(
        string="Provider Resource Name",
        copy=False,
        help="Provider database, collection, schema, or index name. Required for "
        "shared namespace and tenant isolation.",
    )
    connection_uri = fields.Char(
        string="Data-plane Connection URI",
        copy=False,
        groups="llm.group_llm_manager",
        help="Optional database-specific endpoint. Do not embed credentials in this URI.",
    )
    database_user = fields.Char(
        string="Data-plane User",
        copy=False,
        groups="llm.group_llm_manager",
        help="Optional child or service account for direct database access.",
    )
    database_secret = fields.Char(
        string="Data-plane Secret",
        copy=False,
        groups="llm.group_llm_manager",
        help="Credential for the database child or service account.",
    )
    index_configuration = fields.Json(
        help="Backend-specific index and tuning parameters for this vector library.",
    )
    isolation_mode = fields.Selection(
        [
            ("database", "Dedicated Provider Resource"),
            ("namespace", "Shared Resource / Namespace"),
            ("tenant", "Shared Resource / Provider Tenant"),
        ],
        required=True,
        default="database",
        tracking=True,
        help="Provider isolation boundary for this logical vector library.",
    )
    tenant_key = fields.Char(
        string="Isolation Key",
        copy=False,
        index=True,
        help="Namespace or tenant discriminator. Required only for shared isolation.",
    )
    query_contract = fields.Json(
        default=dict,
        copy=False,
        help="Versioned, non-secret provider query contract exposed to direct clients.",
    )
    query_ids = fields.One2many(
        "llm.store.database.query",
        "database_id",
        string="Query Interfaces",
    )
    state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("provisioning", "Provisioning"),
            ("building", "Building"),
            ("maintenance", "Maintenance"),
            ("ready", "Ready"),
            ("error", "Error"),
        ],
        default="draft",
        required=True,
        copy=False,
        tracking=True,
    )
    last_error = fields.Text(readonly=True, copy=False)
    vector_ids = fields.One2many(
        "llm.knowledge.vector",
        "database_id",
        string="Build Configuration",
    )
    build_count = fields.Integer(compute="_compute_build_count")
    record_ids = fields.One2many(
        "llm.store.database.record",
        "database_id",
        string="Provider Records",
    )
    record_count = fields.Integer(compute="_compute_record_count")

    _unique_uuid = models.Constraint(
        "UNIQUE(uuid)",
        "Store database UUIDs must be unique.",
    )
    _unique_backend_key_per_store = models.Constraint(
        "UNIQUE(store_id, backend_key)",
        "Backend database keys must be unique per store instance.",
    )

    @api.depends("vector_ids")
    def _compute_build_count(self):
        for database in self:
            database.build_count = len(database.vector_ids)

    @api.depends("record_ids", "record_ids.state", "record_ids.active")
    def _compute_record_count(self):
        for database in self:
            database.record_count = len(
                database.record_ids.filtered(
                    lambda record: record.active and record.state == "synced"
                )
            )

    @api.constrains(
        "knowledge_collection_id",
        "chunkset_id",
        "dense_embedding_model_id",
        "sparse_embedding_model_id",
        "dimension",
        "isolation_mode",
        "tenant_key",
        "database_name",
    )
    def _check_build_method(self):
        for database in self:
            default_collections = self.env["llm.knowledge.collection"].search(
                [("default_database_id", "=", database.id)]
            )
            if default_collections.filtered(
                lambda collection: collection != database.knowledge_collection_id
            ):
                raise ValidationError(
                    _("A default database must remain in its knowledge collection.")
                )
            if (
                database.chunkset_id
                and database.chunkset_id.collection_id
                != database.knowledge_collection_id
            ):
                raise ValidationError(
                    _(
                        "Chunking configuration '%(chunkset)s' does not belong to "
                        "knowledge collection '%(collection)s'.",
                        chunkset=database.chunkset_id.name,
                        collection=database.knowledge_collection_id.name,
                    )
                )
            embedding_models = (
                database.dense_embedding_model_id
                | database.sparse_embedding_model_id
            )
            if not embedding_models:
                raise ValidationError(
                    _(
                        "Database '%s' needs a dense or sparse embedding model.",
                        database.name,
                    )
                )
            invalid_models = embedding_models.filtered(
                lambda model: model.model_use != "embedding"
            )
            if invalid_models:
                raise ValidationError(
                    _(
                        "Model '%s' is not an embedding model.",
                        invalid_models[0].name,
                    )
                )
            if (
                database.dense_embedding_model_id
                and database.dense_embedding_model_id.embedding_type != "dense"
            ):
                raise ValidationError(
                    _(
                        "Model '%s' is not a dense embedding model.",
                        database.dense_embedding_model_id.name,
                    )
                )
            if (
                database.sparse_embedding_model_id
                and database.sparse_embedding_model_id.embedding_type != "sparse"
            ):
                raise ValidationError(
                    _(
                        "Model '%s' is not a sparse embedding model.",
                        database.sparse_embedding_model_id.name,
                    )
                )
            isolation_key = (database.tenant_key or "").strip()
            if database.isolation_mode == "database" and isolation_key:
                raise ValidationError(
                    _("Dedicated provider resources cannot define an isolation key.")
                )
            if database.isolation_mode in ("namespace", "tenant"):
                if not isolation_key:
                    raise ValidationError(
                        _("Shared namespace and tenant isolation require an isolation key.")
                    )
                if not (database.database_name or "").strip():
                    raise ValidationError(
                        _("Shared isolation requires the provider resource name.")
                    )
                duplicate_scope = self.search_count(
                    [
                        ("store_id", "=", database.store_id.id),
                        ("database_name", "=", database.database_name),
                        ("isolation_mode", "=", database.isolation_mode),
                        ("tenant_key", "=", database.tenant_key),
                        ("id", "!=", database.id),
                    ]
                )
                if duplicate_scope:
                    raise ValidationError(
                        _("This provider namespace or tenant is already configured.")
                    )
            if database.dense_embedding_model_id:
                if database.dimension and database.dimension <= 0:
                    raise ValidationError(
                        _("Dense vector dimension must be a positive integer.")
                    )
            elif database.dimension:
                raise ValidationError(
                    _("A sparse-only database cannot define a dense dimension.")
                )

    @api.model_create_multi
    def create(self, vals_list):
        normalized_vals_list = []
        for vals in vals_list:
            values = dict(vals)
            for field_name in ("database_name", "tenant_key"):
                if field_name in values:
                    values[field_name] = (values[field_name] or "").strip() or False
            normalized_vals_list.append(values)
        databases = super().create(normalized_vals_list)
        for database in databases.filtered(lambda record: not record.backend_key):
            database.with_context(allow_backend_key_write=True).write(
                {"backend_key": str(database.id)}
            )
        return databases

    def write(self, vals):
        if "uuid" in vals:
            raise UserError(_("The store database UUID is immutable."))
        if "backend_key" in vals and not self.env.context.get(
            "allow_backend_key_write"
        ):
            raise UserError(_("The backend database key is immutable."))
        if {"database_name", "tenant_key"}.intersection(vals):
            vals = dict(vals)
            for field_name in ("database_name", "tenant_key"):
                if field_name in vals:
                    vals[field_name] = (vals[field_name] or "").strip() or False

        method_fields = {
            "store_id",
            "knowledge_collection_id",
            "chunkset_id",
            "dense_embedding_model_id",
            "sparse_embedding_model_id",
            "dimension",
            "database_name",
            "index_configuration",
            "isolation_mode",
            "tenant_key",
        }
        if method_fields.intersection(vals):
            provisioned = self.filtered(lambda database: database.state != "draft")
            if provisioned:
                raise UserError(
                    _(
                        "Drop provisioned databases before changing their instance, "
                        "knowledge collection, or build method."
                    )
                )
            if "dense_embedding_model_id" in vals:
                vals = dict(vals, dimension=False)

        result = super().write(vals)
        if method_fields.intersection(vals):
            self.mapped("vector_ids").write({"state": "draft"})
        return result

    def copy_data(self, default=None):
        default = dict(
            default or {},
            backend_key=False,
            database_name=False,
            connection_uri=False,
            database_user=False,
            database_secret=False,
            tenant_key=False,
            query_contract={},
            state="draft",
            last_error=False,
        )
        return super().copy_data(default=default)

    def _backend_metadata(self):
        """Return non-secret provisioning metadata for the provider."""
        self.ensure_one()
        metadata = dict(self.metadata or {})
        metadata.update(self.index_configuration or {})
        if self.database_name:
            metadata["database_name"] = self.database_name
        metadata.update(
            {
                "isolation_mode": self.isolation_mode,
                "isolation_key": self.tenant_key or None,
                "tenant_key": self.tenant_key or None,
                "text_payload_field": "text",
                "query_contract": dict(self.query_contract or {}),
            }
        )
        return metadata

    def _record_identity(self, chunk):
        """Return stable logical and provider IDs for one database/chunk pair."""
        self.ensure_one()
        namespace = uuid_lib.UUID(self.uuid)
        logical_id = str(uuid_lib.uuid5(namespace, chunk.uuid))
        backend_id = str(uuid_lib.uuid5(namespace, f"backend:{logical_id}"))
        return logical_id, backend_id

    @staticmethod
    def _payload_checksum(payload):
        encoded = json.dumps(
            payload or {},
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            default=str,
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def _prepare_database_records(self, chunks, payloads):
        """Create/update pending mappings and provider payload identities."""
        self.ensure_one()
        Record = self.env["llm.store.database.record"].with_context(
            allow_database_record_mutation=True
        )
        existing = Record.search(
            [
                ("database_id", "=", self.id),
                ("chunk_id", "in", chunks.ids),
            ]
        )
        by_chunk = {record.chunk_id.id: record for record in existing}
        ordered_record_ids = []
        provider_payloads = []

        for chunk, payload in zip(chunks, payloads):  # noqa: B905
            original_payload = dict(payload or {})
            text = str(original_payload.get("text") or "")
            logical_id, generated_backend_id = self._record_identity(chunk)
            record = by_chunk.get(chunk.id)
            values = {
                "database_id": self.id,
                "chunk_id": chunk.id,
                "logical_id": logical_id,
                "content_checksum": hashlib.sha256(text.encode("utf-8")).hexdigest(),
                "payload_checksum": self._payload_checksum(original_payload),
                "state": "pending",
                "active": True,
                "last_error": False,
            }
            if record:
                record.write(values)
            else:
                values["backend_id"] = generated_backend_id
                record = Record.create(values)
            ordered_record_ids.append(record.id)

            provider_payload = dict(original_payload)
            provider_payload.update(
                {
                    "logical_id": record.logical_id,
                    "backend_id": record.backend_id,
                    "store_database_id": self.id,
                    "chunk_id": chunk.id,
                }
            )
            provider_payloads.append(provider_payload)

        return Record.browse(ordered_record_ids), provider_payloads

    def _mark_database_records_synced(self, records, provider_result):
        """Validate provider confirmation and mark a completed upsert."""
        self.ensure_one()
        if provider_result is True:
            returned = None
        elif isinstance(provider_result, dict):
            if "records" in provider_result:
                returned = provider_result["records"]
            elif "ids" in provider_result:
                returned = provider_result["ids"]
            else:
                raise UserError(
                    _("The provider upsert response has no record IDs or confirmation.")
                )
        elif isinstance(provider_result, (list, tuple)):
            returned = provider_result
        else:
            raise UserError(_("The provider did not confirm record upsert."))

        if returned is not None:
            if len(returned) != len(records):
                raise UserError(
                    _("The provider returned an unexpected number of record IDs.")
                )
            for record, result in zip(records, returned):  # noqa: B905
                if isinstance(result, dict):
                    backend_id = result.get("backend_id") or result.get("id")
                    provider_metadata = result.get("metadata")
                else:
                    backend_id = result
                    provider_metadata = None
                values = {}
                if backend_id is not None:
                    returned_backend_id = str(backend_id)
                    if returned_backend_id != record.backend_id:
                        raise UserError(
                            _(
                                "Providers must preserve the client-supplied ID for "
                                "record '%(record)s': expected %(expected)s, got "
                                "%(returned)s.",
                                record=record.logical_id,
                                expected=record.backend_id,
                                returned=returned_backend_id,
                            )
                        )
                    values["backend_id"] = returned_backend_id
                if provider_metadata is not None:
                    values["provider_metadata"] = provider_metadata
                if values:
                    record.write(values)

        records.write(
            {
                "state": "synced",
                "active": True,
                "synced_once": True,
                "last_error": False,
            }
        )
        self.vector_count = self.env["llm.store.database.record"].search_count(
            [
                ("database_id", "=", self.id),
                ("state", "=", "synced"),
                ("active", "=", True),
            ]
        )
        return True

    def _normalize_database_results(self, provider_results):
        """Map provider IDs to owned chunks and discard foreign/stale hits."""
        self.ensure_one()
        provider_results = provider_results or []
        backend_ids = [
            str(result["id"])
            for result in provider_results
            if isinstance(result, dict) and result.get("id") is not None
        ]
        records = self.env["llm.store.database.record"].search(
            [
                ("database_id", "=", self.id),
                ("backend_id", "in", backend_ids),
                ("state", "=", "synced"),
                ("active", "=", True),
            ]
        )
        by_backend_id = {record.backend_id: record for record in records}
        normalized = []
        for result in provider_results:
            if not isinstance(result, dict):
                continue
            provider_id = result.get("id")
            if provider_id is None:
                continue
            record = by_backend_id.get(str(provider_id))
            if not record:
                _logger.warning(
                    "Ignoring unowned provider hit %s for database %s",
                    provider_id,
                    self.id,
                )
                continue
            hit = dict(result)
            hit.update(
                {
                    "id": record.chunk_id.id,
                    "logical_id": record.logical_id,
                    "backend_id": record.backend_id,
                    "database_id": self.id,
                }
            )
            normalized.append(hit)
        return normalized

    def _get_default_query(self):
        """Return the active default query interface, or the sole active interface."""
        self.ensure_one()
        active_queries = self.query_ids.filtered("active")
        default_query = active_queries.filtered("is_default")[:1]
        if default_query:
            return default_query
        if len(active_queries) == 1:
            return active_queries
        return self.env["llm.store.database.query"]

    def retrieve(
        self,
        query_text=None,
        query_vector=None,
        query_interface=None,
        limit=10,
        filter=None,
        **kwargs,
    ):
        """Query through an explicit interface or this database's unambiguous default."""
        self.ensure_one()
        if self.state != "ready":
            raise UserError(
                _(
                    "Database '%s' is offline for provisioning or maintenance.",
                    self.name,
                )
            )
        query = query_interface or self._get_default_query()
        if isinstance(query, int):
            query = self.env["llm.store.database.query"].browse(query).exists()
        if not query:
            raise UserError(
                _(
                    "Database '%s' needs one active default query interface.",
                    self.name,
                )
            )
        if query.database_id != self:
            raise UserError(_("The query interface belongs to another database."))
        return query.search_database(
            query_text=query_text,
            query_vector=query_vector,
            limit=limit,
            filter=filter,
            **kwargs,
        )

    def action_view_records(self):
        self.ensure_one()
        return {
            "name": _("Provider Records"),
            "type": "ir.actions.act_window",
            "res_model": "llm.store.database.record",
            "view_mode": "list,form",
            "domain": [("database_id", "=", self.id)],
            "context": {"default_database_id": self.id},
        }

    def _ensure_vector(self):
        """Return this database's single build execution record."""
        self.ensure_one()
        vector = self.vector_ids[:1]
        if vector:
            return vector
        return self.env["llm.knowledge.vector"].create({"database_id": self.id})

    def action_initialize(self):
        """Provision this database through the instance administrator adapter."""
        for database in self:
            if database.dense_embedding_model_id and not database.dimension:
                raise UserError(
                    _(
                        "Set or infer the dense vector dimension before provisioning "
                        "database '%s'.",
                        database.name,
                    )
                )
            previous_state = database.state
            database.write({"state": "provisioning", "last_error": False})
            try:
                exists = database.store_id.database_exists(database)
                if previous_state == "error" and exists:
                    raise UserError(
                        _(
                            "Database '%s' may contain a partial failed build. "
                            "Drop or rebuild it instead of publishing it as ready.",
                            database.name,
                        )
                    )
                if not exists:
                    created = database.store_id.provision_database(database)
                    if not created:
                        raise UserError(
                            _("The store adapter did not provision database '%s'.", database.name)
                        )
                final_state = self.env.context.get("database_ready_state", "ready")
                database.write({"state": final_state, "last_error": False})
            except Exception as error:
                database.write({"state": "error", "last_error": str(error)})
                raise
        return True

    def action_drop(self):
        """Drop the provider scope; keep the Odoo configuration reusable."""
        for database in self:
            database.write({"state": "maintenance", "last_error": False})
            try:
                if database.store_id.database_exists(database):
                    dropped = database.store_id.drop_database(database)
                    if dropped is False:
                        raise UserError(
                            _("The store adapter did not drop database '%s'.", database.name)
                        )
                database.record_ids.with_context(
                    allow_database_record_mutation=True
                ).unlink()
                database.write(
                    {"state": "draft", "last_error": False, "vector_count": 0}
                )
                database.vector_ids.write({"state": "draft"})
            except Exception as error:
                database.write({"state": "error", "last_error": str(error)})
                raise
        return True

    def action_build(self):
        """Build this database from its configured knowledge collection."""
        for database in self:
            database._ensure_vector().action_build()
        return True

    def action_rebuild(self):
        """Drop and rebuild this isolated database variant."""
        for database in self:
            database.action_drop()
            database.action_build()
        return True

    def unlink(self):
        for database in self.filtered(
            lambda record: record.state != "draft" or record.record_ids
        ):
            # Cleanup failures deliberately block deletion so ownership of a
            # remote resource is never lost from Odoo.
            database.action_drop()
        return super().unlink()
