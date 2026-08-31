"""Base component for LLM vector store adapters.

One adapter per store service (``pgvector``, ``qdrant``, ...), selected by
``llm.store._get_adapter()`` through the component ``_usage``, which must equal
the value stored in ``llm.store.service``.

A concrete adapter looks like::

    from odoo.addons.component.core import Component

    class PgvectorStoreAdapter(Component):
        _name = "pgvector.store.adapter"
        _inherit = "llm.store.adapter"       # inherits _collection
        _usage = "pgvector"                  # == llm.store.service

        def create_collection(self, store, collection_id, dimension=None,
                              metadata=None, **kwargs):
            ...

Every method receives the ``llm.store`` record as its first positional
argument, so an adapter never reads ``self.collection`` and stays unit-testable
without a database.
"""

from odoo.addons.component.core import AbstractComponent


class LLMStoreAdapter(AbstractComponent):
    """Service adapter contract for ``llm.store``.

    Unlike ``llm.provider.adapter``, **every** contract is declared here.
    Nothing in ``llm.store._SERVICE_CONTRACT`` is probed with
    ``_has_service_method``, so there is no fallback for a stub to break:
    ``llm.store._OPTIONAL_SERVICE_CONTRACT`` is empty.

    An adapter that omits one of these inherits the stub and raises
    ``NotImplementedError`` when that contract is dispatched -- which is what
    ``_dispatch`` did for a missing attribute anyway.
    """

    _name = "llm.store.adapter"
    # Scope lookups to llm.store: a component with no _collection is returned
    # for every collection in the database.
    _collection = "llm.store"

    def _not_implemented(self, method):
        raise NotImplementedError(
            f"Store adapter '{self._usage}' ({self._name}) does not "
            f"implement {method}()"
        )

    def sanitize_collection_name(self, store, name):
        """Adapt ``name`` to the backend's collection naming rules.

        Mandatory. ``llm.store._default_sanitize_collection_name`` implements
        the common rules and can be called from here (``llm_qdrant`` does), but
        the model never applies it on its own.
        """
        return self._not_implemented("sanitize_collection_name")

    def create_collection(
        self, store, collection_id, dimension=None, metadata=None, **kwargs
    ):
        """Create a collection and return its info dict."""
        return self._not_implemented("create_collection")

    def delete_collection(self, store, collection_id, **kwargs):
        """Drop a collection."""
        return self._not_implemented("delete_collection")

    def list_collections(self, store, **kwargs):
        """Return the existing collections."""
        return self._not_implemented("list_collections")

    def collection_exists(self, store, name, **kwargs):
        """Return whether a collection is present."""
        return self._not_implemented("collection_exists")

    def insert_vectors(
        self, store, collection_id, vectors, metadata=None, ids=None, **kwargs
    ):
        """Upsert vectors with their payload."""
        return self._not_implemented("insert_vectors")

    def delete_vectors(self, store, collection_id, ids, **kwargs):
        """Remove vectors by id."""
        return self._not_implemented("delete_vectors")

    def search_vectors(
        self, store, collection_id, query_vector, limit=10, filter=None, **kwargs
    ):
        """Nearest-neighbour search.

        NOTE: ``llm.store._search_vectors`` dispatches these positionally, and
        the adapters disagree on the fourth parameter's name --
        ``llm_pgvector`` calls it ``filters``, ``llm_qdrant`` ``filter``.
        Positional dispatch hides the divergence; passing it by keyword would
        break one of them.
        """
        return self._not_implemented("search_vectors")

    def create_index(self, store, collection_id, index_type=None, **kwargs):
        """Build a backend index."""
        return self._not_implemented("create_index")
