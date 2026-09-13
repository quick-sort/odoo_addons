"""Store-instance, chunkset-database, and provider-record domain model.

This module is the architecture source of truth for the provider-neutral
``llm.store`` domain owned by ``llm_knowledge``.

Resource relationships::

    llm.knowledge.collection
      1 ─── N llm.knowledge.chunkset
                  1 ─── N llm.store.database
                                   N ─── 1 llm.store
                                   1 ─── 1 llm.knowledge.vector
                                   1 ─── N llm.store.database.query
                                   1 ─── N llm.store.database.record
                                                   N ─── 1 llm.store.chunk

The terms are deliberately separate:

* ``llm.store`` represents a deployment, cluster, server, or SaaS account. It
  owns administrator connectivity and may host many databases.
* ``llm.knowledge.collection`` (KB) owns source documents and any number of
  alternative chunking methods. It only selects an optional
  ``default_database_id`` for retrieval.
* ``llm.knowledge.chunkset`` is one split method for one KB. It may be built
  into any number of independently queryable ``llm.store.database`` records.
* ``llm.store.database`` is a logical vector library for that chunkset. It owns
  optional dense and sparse embedding models, one dense dimension, query
  interfaces, and isolation settings. A provider may implement it as a physical
  database/collection or as a namespace/tenant inside a shared resource.
* ``llm.knowledge.vector`` executes the database build but does not own backend
  lifecycle, embedding configuration, or provider identity.
* ``llm.store.database.record`` maps one database and chunk to a stable
  logical ID and the actual provider record ID.

Invariants enforced by the models and documented by tests:

1. A KB has many chunksets; each chunkset belongs to one KB and may be
   indexed into many databases. Every database and chunkset names the same KB.
2. A database belongs to one store instance and configures at least one dense
   or sparse embedding model. Dense output has one immutable positive dimension
   once provisioned; query interfaces and tenant/namespace isolation belong to
   the database.
3. Store and embedding settings belong only to the database, never to the KB.
4. A chunk has a stable Odoo UUID. Provider identity is database scoped; raw
   Odoo row IDs are never used as provider IDs.
5. Writes, deletes, and query hits cross the provider boundary through
   ``llm.store.database.record``. Foreign, stale, and unsynchronized hits are
   discarded before knowledge code receives them.
6. Only ``llm.store.database`` provisions or drops a backend scope. Cleanup
   failures preserve pre-existing Odoo ownership so remote resources remain
   discoverable and cleanup can be retried.
7. Provider adapters implement the database-level contract directly, accept
   dense and/or sparse vectors, apply database scope before ranking/limit, and
   make record deletion idempotent. There is no legacy collection interface.
"""

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
    active = fields.Boolean(
        default=True,
        tracking=True,
        help="Archives this configuration from normal selection; it does not delete "
        "or disable the remote service.",
    )
    connection_uri = fields.Char(
        string="Administrator Connection URI",
        copy=False,
        groups="llm.group_llm_manager",
        help="Control-plane endpoint used only to provision databases and child "
        "accounts. Do not embed credentials in this URI.",
    )
    admin_user = fields.Char(
        string="Administrator User",
        copy=False,
        groups="llm.group_llm_manager",
    )
    api_key = fields.Char(
        string="Administrator Secret",
        copy=False,
        groups="llm.group_llm_manager",
        help="Control-plane credential. It is never copied or tracked in chatter.",
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
        self,
        database,
        vectors=None,
        sparse_vectors=None,
        metadata=None,
        ids=None,
        **kwargs,
    ):
        self._check_database_owner(database)
        return self._dispatch(
            "insert_database_vectors",
            database,
            vectors,
            sparse_vectors=sparse_vectors,
            metadata=metadata,
            ids=ids,
            **kwargs,
        )

    def _delete_database_vectors(self, database, ids, **kwargs):
        self._check_database_owner(database)
        return self._dispatch("delete_database_vectors", database, ids, **kwargs)

    def _search_database_vectors(
        self, database, query_vector=None, limit=10, filter=None, **kwargs
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
