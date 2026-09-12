"""Base component contract for LLM store adapters.

``llm.store`` is an administrative store *instance*.  The primary resource
managed inside it is ``llm.store.database``: one isolated physical database,
collection, schema, index or namespace (depending on the provider) that holds
exactly one logical knowledge collection.

The database-level methods below are the primary contract. Their default
implementations bridge to collection-oriented methods so existing provider
adapters remain usable. Providers that support child accounts, per-database
endpoints, or native database provisioning should override the database-level
methods and read those settings from the supplied ``database`` record.
"""

from odoo.addons.component.core import AbstractComponent


class LLMStoreAdapter(AbstractComponent):
    """Service adapter contract for ``llm.store`` instances."""

    _name = "llm.store.adapter"
    _collection = "llm.store"

    def _not_implemented(self, method):
        raise NotImplementedError(
            f"Store adapter '{self._usage}' ({self._name}) does not "
            f"implement {method}()"
        )

    # ------------------------------------------------------------------
    # Database-level control plane (primary contract)
    # ------------------------------------------------------------------
    def provision_database(self, store, database, **kwargs):
        """Provision one physical database for one knowledge collection.

        Compatibility providers map it to their old backend collection using
        ``database.backend_key``.  A native implementation may additionally
        create a child account and database-specific credentials.
        """
        return self.create_collection(
            store,
            database._backend_collection_key(),
            dimension=database.dimension,
            metadata=database._backend_metadata(),
            **kwargs,
        )

    def drop_database(self, store, database, **kwargs):
        return self.delete_collection(
            store, database._backend_collection_key(), **kwargs
        )

    def database_exists(self, store, database, **kwargs):
        return self.collection_exists(
            store, database._backend_collection_key(), **kwargs
        )

    def insert_database_vectors(
        self, store, database, vectors, metadata=None, ids=None, **kwargs
    ):
        return self.insert_vectors(
            store,
            database._backend_collection_key(),
            vectors,
            metadata,
            ids,
            **kwargs,
        )

    def delete_database_vectors(self, store, database, ids, **kwargs):
        return self.delete_vectors(
            store, database._backend_collection_key(), ids, **kwargs
        )

    def search_database_vectors(
        self, store, database, query_vector, limit=10, filter=None, **kwargs
    ):
        # Keep the filter positional: legacy pgvector and Qdrant adapters use
        # different parameter names for it.
        return self.search_vectors(
            store,
            database._backend_collection_key(),
            query_vector,
            limit,
            filter,
            **kwargs,
        )

    def create_database_index(
        self, store, database, index_type=None, **kwargs
    ):
        return self.create_index(
            store,
            database._backend_collection_key(),
            index_type,
            **kwargs,
        )

    # ------------------------------------------------------------------
    # Legacy backend-collection contract (compatibility bridge)
    # ------------------------------------------------------------------
    def sanitize_collection_name(self, store, name):
        return self._not_implemented("sanitize_collection_name")

    def create_collection(
        self, store, collection_id, dimension=None, metadata=None, **kwargs
    ):
        return self._not_implemented("create_collection")

    def delete_collection(self, store, collection_id, **kwargs):
        return self._not_implemented("delete_collection")

    def list_collections(self, store, **kwargs):
        return self._not_implemented("list_collections")

    def collection_exists(self, store, name, **kwargs):
        return self._not_implemented("collection_exists")

    def insert_vectors(
        self, store, collection_id, vectors, metadata=None, ids=None, **kwargs
    ):
        return self._not_implemented("insert_vectors")

    def delete_vectors(self, store, collection_id, ids, **kwargs):
        return self._not_implemented("delete_vectors")

    def search_vectors(
        self, store, collection_id, query_vector, limit=10, filter=None, **kwargs
    ):
        return self._not_implemented("search_vectors")

    def create_index(self, store, collection_id, index_type=None, **kwargs):
        return self._not_implemented("create_index")
