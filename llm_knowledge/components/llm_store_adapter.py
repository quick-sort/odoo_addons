"""Base component contract for LLM store adapters.

``llm.store`` is an administrative service instance. Every provider operation
receives an ``llm.store.database`` record, which is the logical knowledge-base
scope and owns its store, chunking, embedding, lifecycle, and backend settings.

There is intentionally no collection-oriented compatibility bridge. Provider
addons must implement this database-level contract directly so database and
provider-record ownership cannot be bypassed.
"""

from odoo.addons.component.core import AbstractComponent


class LLMStoreAdapter(AbstractComponent):
    """Required control-plane and data-plane operations for store databases."""

    _name = "llm.store.adapter"
    _collection = "llm.store"

    def _not_implemented(self, method):
        raise NotImplementedError(
            f"Store adapter '{self._usage}' ({self._name}) does not "
            f"implement {method}()"
        )

    def provision_database(self, store, database, **kwargs):
        """Provision the provider scope represented by ``database``."""
        return self._not_implemented("provision_database")

    def drop_database(self, store, database, **kwargs):
        """Delete the provider scope and every record it owns."""
        return self._not_implemented("drop_database")

    def database_exists(self, store, database, **kwargs):
        """Return whether the provider scope exists."""
        return self._not_implemented("database_exists")

    def insert_database_vectors(
        self,
        store,
        database,
        vectors=None,
        sparse_vectors=None,
        metadata=None,
        ids=None,
        **kwargs,
    ):
        """Upsert dense and/or sparse vectors using database-scoped IDs.

        Providers must use every supplied ``ids`` value unchanged and return
        those same IDs (or ``True``). Server-generated replacement IDs are not
        accepted because they cannot survive an outer Odoo transaction rollback.
        """
        return self._not_implemented("insert_database_vectors")

    def delete_database_vectors(self, store, database, ids, **kwargs):
        """Delete database-scoped records by provider ID.

        Deletion must be idempotent: already-missing IDs are successful. This
        makes retries safe when one of several database cleanups fails later.
        """
        return self._not_implemented("delete_database_vectors")

    def search_database_vectors(
        self, store, database, query_vector=None, limit=10, filter=None, **kwargs
    ):
        """Search one database and return hits containing provider IDs.

        Providers must apply the database scope and caller filters before
        ranking and ``limit`` so unrelated records cannot consume results.
        """
        return self._not_implemented("search_database_vectors")

    def create_database_index(self, store, database, index_type=None, **kwargs):
        """Create or refresh an index inside one database scope."""
        return self._not_implemented("create_database_index")
