"""Executable design scenarios for store instances and knowledge databases.

The test names and docstrings intentionally describe the domain model. When a
relationship or lifecycle rule changes, the corresponding scenario must change
with it; prose documentation alone is not the acceptance criterion.
"""

from unittest.mock import patch

from psycopg2 import IntegrityError

from odoo.exceptions import UserError, ValidationError
from odoo.tests import TransactionCase, tagged

from odoo.addons.llm.tests.common import selection_value


class _DatabaseAdapterStub:
    """In-memory control plane used to test ownership without a real backend."""

    def __init__(self, fail_drop=False):
        self.existing_database_ids = set()
        self.calls = []
        self.fail_drop = fail_drop

    def database_exists(self, store, database, **kwargs):
        self.calls.append(("exists", store, database))
        return database.id in self.existing_database_ids

    def provision_database(self, store, database, **kwargs):
        self.calls.append(("provision", store, database))
        self.existing_database_ids.add(database.id)
        return {"backend_key": database.backend_key}

    def drop_database(self, store, database, **kwargs):
        self.calls.append(("drop", store, database))
        if self.fail_drop:
            raise UserError("Simulated backend cleanup failure")
        self.existing_database_ids.discard(database.id)
        return True


@tagged("post_install", "-at_install")
class TestStoreDatabaseDesign(TransactionCase):
    """Record the cardinality, isolation, and lifecycle design as scenarios."""

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        Provider = cls.env["llm.provider"]
        Store = cls.env["llm.store"]

        with selection_value(
            Provider, "service", "store_test_provider", "Store Test Provider"
        ), selection_value(Store, "service", "store_test", "Store Test"):
            cls.provider = Provider.create(
                {"name": "Store Test Provider", "service": "store_test_provider"}
            )
            cls.store = Store.create(
                {"name": "Primary Store Instance", "service": "store_test"}
            )
            cls.other_store = Store.create(
                {"name": "Secondary Store Instance", "service": "store_test"}
            )

        cls.embedding_model = cls.env["llm.model"].create(
            {
                "name": "store-test-embedding",
                "provider_id": cls.provider.id,
                "model_use": "embedding",
            }
        )
        cls.collection = cls.env["llm.knowledge.collection"].create(
            {"name": "Product Documentation"}
        )
        cls.splitter = cls.env["llm.knowledge.splitter"].create(
            {
                "name": "Recursive 500/50",
                "splitter_type": "recursive",
                "chunk_size": 500,
                "chunk_overlap": 50,
            }
        )
        cls.chunkset = cls.env["llm.knowledge.chunkset"].create(
            {
                "name": "Default Chunkset",
                "collection_id": cls.collection.id,
                "splitter_id": cls.splitter.id,
                "is_default": True,
            }
        )

    def _database(self, name="Default Database", **overrides):
        values = {
            "name": name,
            "store_id": self.store.id,
            "knowledge_collection_id": self.collection.id,
            "chunkset_id": self.chunkset.id,
            "embedding_model_id": self.embedding_model.id,
        }
        values.update(overrides)
        return self.env["llm.store.database"].create(values)

    def _use_adapter(self, adapter):
        patcher = patch.object(
            type(self.env["llm.store"]),
            "_get_adapter",
            lambda records: adapter,
        )
        patcher.start()
        self.addCleanup(patcher.stop)
        return adapter

    def _other_collection_with_chunkset(self, suffix="B"):
        collection = self.env["llm.knowledge.collection"].create(
            {"name": f"Other Knowledge Collection {suffix}"}
        )
        chunkset = self.env["llm.knowledge.chunkset"].create(
            {
                "name": f"Other Chunkset {suffix}",
                "collection_id": collection.id,
                "splitter_id": self.splitter.id,
            }
        )
        return collection, chunkset

    def test_instance_hosts_databases_from_different_collections(self):
        """One instance may host isolated libraries for many collections."""
        first = self._database("Product Docs Database")
        other_collection, other_chunkset = self._other_collection_with_chunkset()
        second = self._database(
            "Other Collection Database",
            knowledge_collection_id=other_collection.id,
            chunkset_id=other_chunkset.id,
        )

        self.assertEqual(first.store_id, self.store)
        self.assertEqual(second.store_id, self.store)
        self.assertEqual(set(self.store.database_ids.ids), {first.id, second.id})

    def test_collection_can_have_independent_database_variants(self):
        """One logical collection may be built by multiple comparison methods."""
        first = self._database(
            "Recursive Variant",
            index_configuration={"method": "hnsw"},
        )
        alternate_splitter = self.env["llm.knowledge.splitter"].create(
            {
                "name": "Token 256/32",
                "splitter_type": "token",
                "chunk_size": 256,
                "chunk_overlap": 32,
            }
        )
        alternate_chunkset = self.env["llm.knowledge.chunkset"].create(
            {
                "name": "Token Chunkset",
                "collection_id": self.collection.id,
                "splitter_id": alternate_splitter.id,
            }
        )
        second = self._database(
            "Token Variant",
            chunkset_id=alternate_chunkset.id,
            index_configuration={"method": "ivfflat"},
        )

        self.assertEqual(
            set(self.collection.database_ids.ids), {first.id, second.id}
        )
        self.assertNotEqual(first.chunkset_id, second.chunkset_id)
        self.assertNotEqual(first.index_configuration, second.index_configuration)

    def test_database_cannot_use_another_collections_chunkset(self):
        """A physical database must contain one collection and its own build method."""
        other_collection, _other_chunkset = self._other_collection_with_chunkset()

        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self._database(
                "Invalid Mixed Database",
                knowledge_collection_id=other_collection.id,
                chunkset_id=self.chunkset.id,
            )

    def test_database_has_one_build_execution_record(self):
        """A database is one comparison method, so it cannot own two vector builds."""
        database = self._database()
        build = database._ensure_vector()

        self.assertEqual(build.database_id, database)
        self.assertEqual(build.collection_id, self.collection)
        self.assertEqual(build.chunkset_id, self.chunkset)
        self.assertEqual(build.embedding_model_id, self.embedding_model)
        self.assertEqual(build.store_id, self.store)

        with self.assertRaises(IntegrityError), self.env.cr.savepoint():
            self.env["llm.knowledge.vector"].create(
                {"database_id": database.id}
            )
            self.env.flush_all()

    def test_backend_key_is_owned_by_database_not_build(self):
        """Deleting a build never drops or renames its physical database."""
        adapter = self._use_adapter(_DatabaseAdapterStub())
        database = self._database(dimension=3)
        build = database._ensure_vector()
        database.action_initialize()
        backend_key = database.backend_key
        adapter.calls.clear()

        build.unlink()

        self.assertTrue(database.exists())
        self.assertEqual(database.state, "ready")
        self.assertIn(database.id, adapter.existing_database_ids)
        self.assertFalse(adapter.calls)
        self.assertEqual(database.backend_key, backend_key)
        with self.assertRaises(UserError):
            database.write({"backend_key": "renamed"})
        self.assertFalse(database.vector_ids)
        self.assertEqual(database._ensure_vector().database_id, database)

    def test_database_owns_provision_and_drop_lifecycle(self):
        """Build actions delegate physical creation and deletion to their database."""
        adapter = self._use_adapter(_DatabaseAdapterStub())
        database = self._database(dimension=3)
        build = database._ensure_vector()

        database.action_initialize()
        self.assertEqual(database.state, "ready")
        self.assertIn(database.id, adapter.existing_database_ids)

        adapter.calls.clear()
        build.action_drop()

        self.assertEqual(database.state, "draft")
        self.assertEqual(build.state, "draft")
        self.assertEqual(
            [name for name, _store, _database in adapter.calls],
            ["exists", "drop"],
        )
        self.assertTrue(all(call[2] == database for call in adapter.calls))

    def test_provisioned_database_method_is_immutable_until_drop(self):
        """Ready build settings cannot drift and invalidate comparisons."""
        self._use_adapter(_DatabaseAdapterStub())
        database = self._database(dimension=3)
        database.action_initialize()

        with self.assertRaises(UserError):
            database.write({"dimension": 4})

        database.action_drop()
        database.write({"dimension": 4})
        self.assertEqual(database.dimension, 4)

    def test_cleanup_failure_keeps_database_ownership_record(self):
        """Remote cleanup errors must not leave an untracked orphan database."""
        adapter = self._use_adapter(_DatabaseAdapterStub(fail_drop=True))
        database = self._database(dimension=3)
        database.action_initialize()

        with self.assertRaises(UserError):
            database.unlink()

        self.assertTrue(database.exists())
        self.assertEqual(database.state, "error")
        self.assertIn(database.id, adapter.existing_database_ids)

    def test_instance_cannot_be_deleted_while_it_owns_databases(self):
        """Deleting an administrator instance must not orphan its child databases."""
        self._database()

        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self.store.unlink()
