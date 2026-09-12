"""Tests for the ``llm.store`` adapter contract.

Reads the abstract base component straight out of the component registry, so no
store service has to be registered.
"""

from types import SimpleNamespace
from unittest.mock import patch

from odoo.tests import TransactionCase, tagged

from odoo.addons.component.core import _component_databases

#: Methods every ``llm.store.adapter`` must implement, dispatched by the base
#: model. Hardcoded here rather than read off a class attribute: the contract
#: lives in the code (the base component's stubs, and the model's
#: ``_dispatch`` call sites), not in a separate declaration. Unlike
#: ``llm.provider``, none of these is probed with ``_has_service_method``
#: before dispatch -- there is no optional contract on ``llm.store``.
MANDATORY_CONTRACT = (
    "create_collection",
    "delete_collection",
    "list_collections",
    "collection_exists",
    "sanitize_collection_name",
    "insert_vectors",
    "delete_vectors",
    "search_vectors",
    "create_index",
)

# Primary domain contract. These methods receive an llm.store.database record;
# the base implementations deliberately bridge to MANDATORY_CONTRACT so
# collection-oriented providers remain usable.
DATABASE_CONTRACT = (
    "provision_database",
    "drop_database",
    "database_exists",
    "insert_database_vectors",
    "delete_database_vectors",
    "search_database_vectors",
    "create_database_index",
)


@tagged("post_install", "-at_install")
class TestStoreContract(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Store = cls.env["llm.store"]
        registry = _component_databases[cls.env.cr.dbname]
        cls.adapter_cls = registry["llm.store.adapter"]

    def test_every_contract_is_declared_on_the_base(self):
        """Every collection compatibility operation is explicit on the adapter."""
        missing = [
            name for name in MANDATORY_CONTRACT if not hasattr(self.adapter_cls, name)
        ]

        self.assertFalse(
            missing,
            "llm.store.adapter must declare every contract, missing: %s" % missing,
        )

    def test_declared_stubs_raise_not_implemented(self):
        """An adapter omitting a contract must fail loudly, not silently."""
        adapter = object.__new__(self.adapter_cls)

        with self.assertRaises(NotImplementedError):
            adapter.list_collections(self.Store)

    def test_sanitize_collection_name_is_mandatory(self):
        """It is dispatched unconditionally, despite the default helper.

        ``_default_sanitize_collection_name`` is a helper an adapter may call,
        not a fallback the model applies -- so a store that omits
        ``sanitize_collection_name`` breaks rather than degrading.
        """
        adapter = object.__new__(self.adapter_cls)

        with self.assertRaises(NotImplementedError):
            adapter.sanitize_collection_name(self.Store, "probe")

    def test_database_contract_is_declared_on_the_base(self):
        """Database-oriented providers have one explicit control/data-plane API."""
        missing = [
            name for name in DATABASE_CONTRACT if not hasattr(self.adapter_cls, name)
        ]

        self.assertFalse(
            missing,
            "llm.store.adapter must declare every database contract, missing: %s"
            % missing,
        )

    def test_provision_database_bridges_with_stable_backend_key(self):
        """Collection-oriented providers receive the database-owned backend key."""
        adapter = object.__new__(self.adapter_cls)
        database = SimpleNamespace(
            dimension=3,
            _backend_collection_key=lambda: "database-42",
            _backend_metadata=lambda: {"method": "hnsw"},
        )

        with patch.object(
            self.adapter_cls,
            "create_collection",
            return_value={"name": "database-42"},
        ) as create_collection:
            result = adapter.provision_database(self.Store, database)

        self.assertEqual(result, {"name": "database-42"})
        create_collection.assert_called_once_with(
            self.Store,
            "database-42",
            dimension=3,
            metadata={"method": "hnsw"},
        )

    def test_database_search_keeps_filter_positional_for_providers(self):
        """Pgvector and Qdrant may name the filter argument differently."""
        adapter = object.__new__(self.adapter_cls)
        database = SimpleNamespace(
            _backend_collection_key=lambda: "database-7"
        )
        query = [0.1, 0.2, 0.3]
        metadata_filter = {"language": "en"}

        with patch.object(
            self.adapter_cls,
            "search_vectors",
            return_value=[],
        ) as search_vectors:
            adapter.search_database_vectors(
                self.Store,
                database,
                query,
                limit=5,
                filter=metadata_filter,
            )

        search_vectors.assert_called_once_with(
            self.Store,
            "database-7",
            query,
            5,
            metadata_filter,
        )
