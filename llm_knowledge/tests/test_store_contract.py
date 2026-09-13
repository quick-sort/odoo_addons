"""Executable scenarios for the database-scoped store adapter contract."""

from odoo.tests import TransactionCase, tagged

from odoo.addons.component.core import _component_databases

DATABASE_CONTRACT = (
    "provision_database",
    "drop_database",
    "database_exists",
    "insert_database_vectors",
    "delete_database_vectors",
    "search_database_vectors",
    "create_database_index",
)

LEGACY_COLLECTION_CONTRACT = (
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


@tagged("post_install", "-at_install")
class TestStoreContract(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Store = cls.env["llm.store"]
        registry = _component_databases[cls.env.cr.dbname]
        cls.adapter_cls = registry["llm.store.adapter"]

    def test_database_contract_is_declared_on_the_base(self):
        """Every provider implements one explicit database-scoped API."""
        missing = [
            name for name in DATABASE_CONTRACT if not hasattr(self.adapter_cls, name)
        ]

        self.assertFalse(
            missing,
            "llm.store.adapter must declare every database contract, missing: %s"
            % missing,
        )

    def test_database_contract_stubs_fail_loudly(self):
        """An adapter omitting a database operation cannot silently degrade."""
        adapter = object.__new__(self.adapter_cls)

        for method_name in DATABASE_CONTRACT:
            method = getattr(adapter, method_name)
            with self.subTest(method=method_name), self.assertRaises(
                NotImplementedError
            ):
                if method_name == "insert_database_vectors":
                    method(self.Store, object(), [[0.1]], ids=["record"])
                elif method_name == "delete_database_vectors":
                    method(self.Store, object(), ["record"])
                elif method_name == "search_database_vectors":
                    method(self.Store, object(), [0.1])
                else:
                    method(self.Store, object())

    def test_legacy_collection_contract_is_absent(self):
        """The base adapter cannot bypass database ownership through old methods."""
        present = [
            name
            for name in LEGACY_COLLECTION_CONTRACT
            if hasattr(self.adapter_cls, name)
        ]

        self.assertFalse(
            present,
            "Legacy collection adapter methods must be removed: %s" % present,
        )

    def test_store_model_exposes_only_database_dispatch(self):
        """The store model no longer dispatches collection-oriented operations."""
        present = [
            name
            for name in LEGACY_COLLECTION_CONTRACT
            if hasattr(type(self.Store), name)
        ]

        self.assertFalse(
            present,
            "Legacy collection store methods must be removed: %s" % present,
        )
