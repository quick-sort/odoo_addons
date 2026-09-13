"""Database data-plane facade with persistent provider-ID ownership.

Callers continue to identify Odoo chunks. Before provider dispatch, this mixin
resolves them to ``llm.store.database.record`` rows and sends provider IDs.
Provider search hits are mapped back to chunks before reaching knowledge code.
"""

from odoo import _, fields, models
from odoo.exceptions import UserError


class LLMStoreCollection(models.AbstractModel):
    _name = "llm.store.collection"
    _description = "LLM Store Database Resource"
    _inherit = ["mail.thread"]

    name = fields.Char(required=True, tracking=True)
    store_id = fields.Many2one(
        "llm.store",
        string="Store Instance",
        required=True,
        ondelete="restrict",
        tracking=True,
    )
    dimension = fields.Integer(
        tracking=True,
        help="Embedding dimension used by every dense vector in this database.",
    )
    vector_count = fields.Integer(
        readonly=True,
        copy=False,
        help="Number of active synchronized provider records.",
    )
    metadata = fields.Json(
        string="Database Metadata",
        help="Backend-neutral metadata passed while provisioning the database.",
    )
    description = fields.Text(tracking=True)
    active = fields.Boolean(
        default=True,
        tracking=True,
        help="Archives this logical database configuration without deleting its "
        "provider resource.",
    )

    _unique_name_per_store = models.Constraint(
        "UNIQUE(store_id, name)",
        "Database names must be unique per store instance.",
    )

    def refresh_stats(self):
        return True

    def delete_vectors(self, ids=None):
        """Delete mappings for the given Odoo chunk IDs from the provider."""
        self.ensure_one()
        if not self.store_id:
            return False
        if self.state == "ready":
            self.write({"state": "maintenance"})
        records = self.env["llm.store.database.record"].with_context(
            allow_database_record_mutation=True
        ).search(
            [
                ("database_id", "=", self.id),
                ("chunk_id", "in", ids or []),
            ]
        )
        if not records:
            return True

        records.write({"state": "deleting", "last_error": False})
        try:
            result = self.store_id._delete_database_vectors(
                self, records.mapped("backend_id")
            )
            if result is False:
                raise UserError(
                    _("The provider did not confirm database record deletion.")
                )
        except Exception as error:
            records.write({"state": "error", "last_error": str(error)})
            raise

        records.unlink()
        self.vector_count = self.env["llm.store.database.record"].search_count(
            [
                ("database_id", "=", self.id),
                ("state", "=", "synced"),
                ("active", "=", True),
            ]
        )
        return result

    def search_vectors(self, query_vector=None, limit=10, filter=None, **kwargs):
        """Search one ready database through its configured provider adapter.

        ``query_vector`` remains the dense compatibility input. BM25, sparse,
        and hybrid providers receive text/sparse inputs and execution settings
        through ``kwargs``.
        """
        self.ensure_one()
        if not self.store_id:
            return []
        if self.state != "ready":
            raise UserError(
                _(
                    "Database '%s' is offline for provisioning or maintenance.",
                    self.name,
                )
            )
        results = self.store_id._search_database_vectors(
            self,
            query_vector,
            limit=limit,
            filter=filter,
            **kwargs,
        )
        return self._normalize_database_results(results)

    def _validate_sparse_vectors(self, sparse_vectors):
        """Validate the provider-neutral ``indices``/``values`` sparse shape."""
        for vector in sparse_vectors or []:
            if not isinstance(vector, dict):
                raise UserError(
                    _("Sparse vectors must be mappings with indices and values.")
                )
            indices = vector.get("indices")
            values = vector.get("values")
            if not isinstance(indices, (list, tuple)) or not isinstance(
                values, (list, tuple)
            ):
                raise UserError(
                    _("Sparse vector indices and values must be sequences.")
                )
            if len(indices) != len(values):
                raise UserError(
                    _("Sparse vector indices and values must have equal lengths.")
                )
            if any(not isinstance(index, int) or index < 0 for index in indices):
                raise UserError(_("Sparse vector indices must be non-negative integers."))
            if any(not isinstance(value, (int, float)) for value in values):
                raise UserError(_("Sparse vector values must be numeric."))
        return True

    def insert_vectors(
        self,
        vectors=None,
        sparse_vectors=None,
        metadata=None,
        ids=None,
        **kwargs,
    ):
        """Upsert dense and/or sparse vectors with provider-ID mappings."""
        self.ensure_one()
        if not self.store_id:
            raise UserError(_("No store instance configured for this database."))
        if self.state not in ("draft", "building", "maintenance"):
            raise UserError(
                _(
                    "Database '%s' must be offline before provider records can be "
                    "inserted or replaced.",
                    self.name,
                )
            )
        if not ids:
            raise UserError(_("Every retrieval record needs an Odoo chunk ID."))
        record_count = len(ids)
        if vectors is not None and len(vectors) != record_count:
            raise UserError(_("Dense vector and chunk counts must match."))
        if sparse_vectors is not None and len(sparse_vectors) != record_count:
            raise UserError(_("Sparse vector and chunk counts must match."))
        if sparse_vectors is not None:
            self._validate_sparse_vectors(sparse_vectors)
        if vectors is None and sparse_vectors is None:
            raise UserError(_("Provide dense vectors, sparse vectors, or both."))
        if bool(self.dense_embedding_model_id) != (vectors is not None):
            raise UserError(
                _(
                    "Dense vectors must be present exactly when a dense embedding "
                    "model is configured."
                )
            )
        if bool(self.sparse_embedding_model_id) != (sparse_vectors is not None):
            raise UserError(
                _(
                    "Sparse vectors must be present exactly when a sparse embedding "
                    "model is configured."
                )
            )
        if vectors is not None:
            try:
                dimensions = {len(vector) for vector in vectors}
            except TypeError as error:
                raise UserError(_("Dense vectors must be sized sequences.")) from error
            if len(dimensions) != 1 or next(iter(dimensions), 0) <= 0:
                raise UserError(
                    _("Every dense vector must have one identical positive dimension.")
                )
            detected_dimension = next(iter(dimensions))
            if self.dimension and self.dimension != detected_dimension:
                raise UserError(
                    _(
                        "Dense vectors have dimension %(actual)s, but database "
                        "'%(database)s' is fixed at %(expected)s.",
                        actual=detected_dimension,
                        database=self.name,
                        expected=self.dimension,
                    )
                )
            if not self.dimension:
                self.write({"dimension": detected_dimension})
        payloads = metadata or [{} for _record in ids]
        if len(payloads) != record_count:
            raise UserError(_("Payload and chunk counts must match."))
        for payload in payloads:
            if not isinstance(payload, dict):
                raise UserError(_("Every vector payload must be a mapping."))
            if "text" not in payload or not isinstance(payload["text"], str):
                raise UserError(
                    _("Every vector payload must contain canonical string field 'text'.")
                )

        chunks = self.env["llm.store.chunk"].browse(ids).exists()
        if len(chunks) != record_count or chunks.ids != list(ids):
            raise UserError(_("All record IDs must reference existing Odoo chunks."))
        if any(chunk.chunkset_id != self.chunkset_id for chunk in chunks):
            raise UserError(
                _("All chunks must belong to this database's chunking method.")
            )

        records, provider_payloads = self._prepare_database_records(chunks, payloads)
        try:
            result = self.store_id._insert_database_vectors(
                self,
                vectors,
                sparse_vectors=sparse_vectors,
                metadata=provider_payloads,
                ids=records.mapped("backend_id"),
                **kwargs,
            )
            self._mark_database_records_synced(records, result)
        except Exception as error:
            records.write({"state": "error", "last_error": str(error)})
            raise
        return records.mapped("backend_id")

    def create_index(self, index_type=None, **kwargs):
        self.ensure_one()
        if not self.store_id:
            return False
        return self.store_id._create_database_index(
            self, index_type=index_type, **kwargs
        )
