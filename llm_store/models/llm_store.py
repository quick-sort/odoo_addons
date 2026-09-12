"""Store-instance and knowledge-database domain model.

This module is the architecture source of truth for ``llm_store``.

Resource hierarchy::

    llm.store                         service instance / control plane
      1 ─── N llm.store.database      isolated physical knowledge database
                  N ─── 1 llm.knowledge.collection
                  1 ─── 1 llm.knowledge.vector

The terms are deliberately separate:

* ``llm.store`` represents a deployment, cluster, server, or SaaS tenant. It
  owns the administrator endpoint and credentials used to provision child
  accounts and databases.
* ``llm.store.database`` is the independently configurable and deletable
  isolation boundary inside that instance. A provider may implement it as a
  SQL database/schema/table, vector collection, index, namespace, or directory.
* ``llm.knowledge.collection`` owns logical source documents. One collection
  may be built into several databases using different chunking, embedding, and
  index methods so quality, latency, cost, and storage can be compared.
* ``llm.knowledge.vector`` is only the build/search execution layer. It never
  owns the backend resource lifecycle.

Invariants enforced by the models and documented by tests:

1. A store instance may host databases for many knowledge collections.
2. A store database belongs to exactly one instance and exactly one knowledge
   collection.
3. A store database records exactly one chunkset/embedding/index build method
   and has at most one vector build execution record.
4. Only ``llm.store.database`` provisions or drops a physical backend resource.
5. A provisioned database must be dropped before structural configuration is
   changed, and cleanup failure must not lose the owning Odoo record.
6. Provider adapters receive the database record. Collection-oriented provider
   methods remain a compatibility facade keyed by ``database.backend_key``.
"""

import re

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class LLMStore(models.Model):
    _name = "llm.store"
    _inherit = ["mail.thread", "collection.base", "llm.service.dispatch.mixin"]
    _description = "LLM Store Instance"

    # One record represents a service deployment/cluster/tenant and its
    # administrator connection.  Physical knowledge databases are separate
    # llm.store.database records and may have their own child credentials.
    name = fields.Char(required=True, tracking=True)
    service = fields.Selection(
        selection=[],
        required=True,
        tracking=True,
        help="Provider adapter for this store service instance.",
    )
    active = fields.Boolean(default=True, tracking=True)
    connection_uri = fields.Char(
        string="Administrator Connection URI",
        tracking=True,
        help="Control-plane endpoint used to provision databases and child accounts.",
    )
    admin_user = fields.Char(
        string="Administrator User",
        tracking=True,
    )
    api_key = fields.Char(
        string="Administrator Secret",
        tracking=True,
    )
    metadata = fields.Json(string="Instance Metadata")
    database_ids = fields.One2many(
        "llm.store.database",
        "store_id",
        string="Databases",
    )
    database_count = fields.Integer(compute="_compute_database_count")

    @api.depends("database_ids")
    def _compute_database_count(self):
        for store in self:
            store.database_count = len(store.database_ids)

    def action_view_databases(self):
        self.ensure_one()
        return {
            "name": _("Store Databases"),
            "type": "ir.actions.act_window",
            "res_model": "llm.store.database",
            "view_mode": "list,form",
            "domain": [("store_id", "=", self.id)],
            "context": {"default_store_id": self.id},
        }

    def unlink(self):
        for store in self:
            if store.database_ids:
                raise ValidationError(
                    _(
                        "Store instance '%s' still owns databases. Remove them "
                        "before deleting the instance.",
                        store.name,
                    )
                )
        return super().unlink()

    # ------------------------------------------------------------------
    # Database-level control plane
    # ------------------------------------------------------------------
    def _check_database_owner(self, database):
        self.ensure_one()
        database.ensure_one()
        if database.store_id != self:
            raise ValidationError(
                _(
                    "Database '%s' does not belong to this store instance.",
                    database.name,
                )
            )

    def provision_database(self, database, **kwargs):
        self._check_database_owner(database)
        return self._dispatch("provision_database", database, **kwargs)

    def drop_database(self, database, **kwargs):
        self._check_database_owner(database)
        return self._dispatch("drop_database", database, **kwargs)

    def database_exists(self, database, **kwargs):
        self._check_database_owner(database)
        return self._dispatch("database_exists", database, **kwargs)

    def _insert_database_vectors(
        self, database, vectors, metadata=None, ids=None, **kwargs
    ):
        self._check_database_owner(database)
        return self._dispatch(
            "insert_database_vectors",
            database,
            vectors,
            metadata,
            ids,
            **kwargs,
        )

    def _delete_database_vectors(self, database, ids, **kwargs):
        self._check_database_owner(database)
        return self._dispatch("delete_database_vectors", database, ids, **kwargs)

    def _search_database_vectors(
        self, database, query_vector, limit=10, filter=None, **kwargs
    ):
        self._check_database_owner(database)
        return self._dispatch(
            "search_database_vectors",
            database,
            query_vector,
            limit,
            filter,
            **kwargs,
        )

    def _create_database_index(self, database, index_type=None, **kwargs):
        self._check_database_owner(database)
        return self._dispatch(
            "create_database_index", database, index_type, **kwargs
        )

    # ------------------------------------------------------------------
    # Collection-oriented provider compatibility facade
    # ------------------------------------------------------------------
    def create_collection(self, collection_id, dimension=None, metadata=None, **kwargs):
        return self._dispatch(
            "create_collection", collection_id, dimension, metadata, **kwargs
        )

    def delete_collection(self, collection_id, **kwargs):
        return self._dispatch("delete_collection", collection_id, **kwargs)

    def list_collections(self, **kwargs):
        return self._dispatch("list_collections", **kwargs)

    def collection_exists(self, name, **kwargs):
        return self._dispatch("collection_exists", name, **kwargs)

    def _default_sanitize_collection_name(self, name):
        s = name.lower()
        s = re.sub(r"[^a-z0-9._-]", "-", s)
        s = re.sub(r"\.{2,}", ".", s)
        s = s[:63]
        s = re.sub(r"^[^a-z0-9]+", "", s)
        s = re.sub(r"[^a-z0-9]+$", "", s)
        if len(s) < 3:
            s = s.ljust(3, "a")
        return s

    def sanitize_collection_name(self, name):
        return self._dispatch("sanitize_collection_name", name)

    def get_sanitized_collection_name(self, collection_id):
        """Generate a backend-safe legacy collection name."""
        db_name = self.env.cr.dbname
        return self.sanitize_collection_name(f"odoo_{db_name}_{collection_id}")

    def get_santized_collection_name(self, collection_id):
        """Deprecated misspelled alias retained for existing providers."""
        return self.get_sanitized_collection_name(collection_id)

    def _insert_vectors(
        self, collection_id, vectors, metadata=None, ids=None, **kwargs
    ):
        return self._dispatch(
            "insert_vectors", collection_id, vectors, metadata, ids, **kwargs
        )

    def _delete_vectors(self, collection_id, ids, **kwargs):
        return self._dispatch("delete_vectors", collection_id, ids, **kwargs)

    def _search_vectors(
        self, collection_id, query_vector, limit=10, filter=None, **kwargs
    ):
        return self._dispatch(
            "search_vectors", collection_id, query_vector, limit, filter, **kwargs
        )

    def create_index(self, collection_id, index_type=None, **kwargs):
        return self._dispatch("create_index", collection_id, index_type, **kwargs)
