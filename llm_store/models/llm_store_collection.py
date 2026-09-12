"""Reusable data-plane behavior for a physical store database.

``llm.store.collection`` is kept as an abstract compatibility mixin because
provider addons already know the old collection-oriented adapter contract.
Only ``llm.store.database`` should inherit it.  A knowledge vector is a build
configuration and must not own a backend collection/database lifecycle.
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
        help="Embedding dimension used by every vector in this database.",
    )
    vector_count = fields.Integer(
        tracking=True,
        help="Number of vectors reported for this physical database.",
    )
    metadata = fields.Json(
        string="Database Metadata",
        help="Backend-neutral metadata passed while provisioning the database.",
    )
    description = fields.Text(tracking=True)
    active = fields.Boolean(default=True, tracking=True)

    _unique_name_per_store = models.Constraint(
        "UNIQUE(store_id, name)",
        "Database names must be unique per store instance.",
    )

    def _backend_collection_key(self):
        """Return the stable opaque key passed to legacy provider adapters."""
        self.ensure_one()
        return self.backend_key or str(self.id)

    def refresh_stats(self):
        """Extension point for provider-specific database statistics."""
        return True

    def delete_vectors(self, ids=None):
        """Delete vector points from this physical database."""
        self.ensure_one()
        if not self.store_id:
            return False
        return self.store_id._delete_database_vectors(self, ids or [])

    def search_vectors(self, query_vector, limit=10, filter=None, **kwargs):
        """Search this physical database without exposing adapter details."""
        self.ensure_one()
        if not self.store_id:
            return []
        return self.store_id._search_database_vectors(
            self,
            query_vector,
            limit=limit,
            filter=filter,
            **kwargs,
        )

    def insert_vectors(self, vectors, metadata=None, ids=None, **kwargs):
        """Insert vector points into this physical database."""
        self.ensure_one()
        if not self.store_id:
            raise UserError(_("No store instance configured for this database."))
        return self.store_id._insert_database_vectors(
            self,
            vectors,
            metadata=metadata,
            ids=ids,
            **kwargs,
        )

    def create_index(self, index_type=None, **kwargs):
        """Create or refresh this database's backend index."""
        self.ensure_one()
        if not self.store_id:
            return False
        return self.store_id._create_database_index(
            self, index_type=index_type, **kwargs
        )
