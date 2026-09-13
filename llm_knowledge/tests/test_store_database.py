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
    """In-memory database provider used to exercise ownership boundaries."""

    def __init__(self, fail_drop=False, fail_delete=False):
        self.existing_database_ids = set()
        self.calls = []
        self.fail_drop = fail_drop
        self.fail_delete = fail_delete
        self.insert_result = None
        self.search_results = []

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
        self.calls.append(
            (
                "insert",
                store,
                database,
                vectors,
                metadata,
                list(ids or []),
                sparse_vectors,
            )
        )
        if self.insert_result is not None:
            return self.insert_result
        return list(ids or [])

    def delete_database_vectors(self, store, database, ids, **kwargs):
        self.calls.append(("delete_records", store, database, list(ids)))
        if self.fail_delete:
            raise UserError("Simulated provider record cleanup failure")
        return True

    def search_database_vectors(
        self, store, database, query_vector, limit=10, filter=None, **kwargs
    ):
        self.calls.append(
            ("search", store, database, query_vector, limit, filter, kwargs)
        )
        return list(self.search_results)


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
                "name": "store-test-dense-embedding",
                "provider_id": cls.provider.id,
                "model_use": "embedding",
                "embedding_type": "dense",
            }
        )
        cls.sparse_embedding_model = cls.env["llm.model"].create(
            {
                "name": "store-test-sparse-embedding",
                "provider_id": cls.provider.id,
                "model_use": "embedding",
                "embedding_type": "sparse",
            }
        )
        cls.source_backend = cls.env["storage.backend"].create(
            {
                "name": "Store Record Test Files",
                "backend_type": "filesystem",
                "directory_path": "llm_store_record_tests",
            }
        )
        cls.collection = cls.env["llm.knowledge.collection"].create(
            {
                "name": "Product Documentation",
                "source_backend_id": cls.source_backend.id,
            }
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

    def setUp(self):
        super().setUp()
        self._document_sequence = 0

    def _database(self, name="Default Database", **overrides):
        values = {
            "name": name,
            "store_id": self.store.id,
            "knowledge_collection_id": self.collection.id,
            "chunkset_id": self.chunkset.id,
            "dense_embedding_model_id": self.embedding_model.id,
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

    def _chunk(self, sequence=1, chunkset=None):
        self._document_sequence += 1
        chunkset = chunkset or self.chunkset
        document = self.env["llm.document"].create(
            {
                "name": f"Mapping Document {self._document_sequence}",
                "collection_id": chunkset.collection_id.id,
                "source_type": "file",
                "source_backend_id": self.source_backend.id,
                "source_path": f"mapping-{self._document_sequence}.md",
            }
        )
        chunk = self.env["llm.store.chunk"].create(
            {
                "document_id": document.id,
                "chunkset_id": chunkset.id,
                "sequence": sequence,
            }
        )
        return document, chunk

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
        self.assertEqual(build.dense_embedding_model_id, self.embedding_model)
        self.assertFalse(build.sparse_embedding_model_id)
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

        with self.assertRaises(UserError), self.env.cr.savepoint():
            database.unlink()

        self.assertTrue(database.exists())
        self.assertEqual(database.state, "ready")
        self.assertFalse(database.last_error)
        self.assertIn(database.id, adapter.existing_database_ids)

    def test_instance_cannot_be_deleted_while_it_owns_databases(self):
        """Deleting an administrator instance must not orphan its child databases."""
        self._database()

        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self.store.unlink()


    def test_insert_creates_stable_provider_record_mapping(self):
        """An upsert maps stable chunk identity to a database-scoped provider ID."""
        adapter = self._use_adapter(_DatabaseAdapterStub())
        database = self._database()
        _document, chunk = self._chunk()

        returned_ids = database.insert_vectors(
            [[0.1, 0.2, 0.3]],
            metadata=[{"text": "Alpha", "language": "en"}],
            ids=[chunk.id],
        )

        record = database.record_ids
        self.assertEqual(len(record), 1)
        self.assertEqual(record.chunk_id, chunk)
        self.assertEqual(record.state, "synced")
        self.assertEqual(returned_ids, [record.backend_id])
        self.assertNotEqual(record.backend_id, str(chunk.id))
        self.assertTrue(record.logical_id)
        insert_call = next(call for call in adapter.calls if call[0] == "insert")
        self.assertEqual(insert_call[5], [record.backend_id])
        self.assertEqual(insert_call[4][0]["logical_id"], record.logical_id)
        self.assertEqual(insert_call[4][0]["backend_id"], record.backend_id)

    def test_chunkset_can_be_indexed_into_multiple_databases(self):
        """One chunkset may be compared across independent vector databases."""
        first = self._database("First Mapping Database")
        second = self._database("Second Mapping Database")

        self.assertNotEqual(first, second)
        self.assertEqual(first.chunkset_id, second.chunkset_id)
        self.assertEqual(len(first.chunkset_id.database_ids), 2)

    def test_upsert_reuses_stable_provider_id_and_updates_checksums(self):
        """Updating a chunk reuses its deterministic database-scoped ID."""
        adapter = self._use_adapter(_DatabaseAdapterStub())
        database = self._database()
        _document, chunk = self._chunk()

        database.insert_vectors(
            [[0.1]], metadata=[{"text": "First text"}], ids=[chunk.id]
        )
        record = database.record_ids
        first_record_id = record.id
        stable_backend_id = record.backend_id
        first_checksum = record.content_checksum
        adapter.calls.clear()

        database.insert_vectors(
            [[0.2]], metadata=[{"text": "Updated text"}], ids=[chunk.id]
        )

        self.assertEqual(database.record_ids.id, first_record_id)
        self.assertEqual(database.record_ids.backend_id, stable_backend_id)
        self.assertNotEqual(database.record_ids.content_checksum, first_checksum)
        insert_call = next(call for call in adapter.calls if call[0] == "insert")
        self.assertEqual(insert_call[5], [stable_backend_id])
        self.assertEqual(insert_call[4][0]["backend_id"], stable_backend_id)

    def test_delete_uses_backend_id_and_removes_mapping(self):
        """Deleting a chunk record sends provider IDs and clears only its mapping."""
        adapter = self._use_adapter(_DatabaseAdapterStub())
        database = self._database()
        _document, chunk = self._chunk()
        database.insert_vectors([[0.1]], metadata=[{"text": "Alpha"}], ids=[chunk.id])
        backend_id = database.record_ids.backend_id
        adapter.calls.clear()

        database.delete_vectors(ids=[chunk.id])

        self.assertFalse(database.record_ids)
        self.assertEqual(database.vector_count, 0)
        self.assertEqual(adapter.calls[0][0], "delete_records")
        self.assertEqual(adapter.calls[0][3], [backend_id])

    def test_query_maps_owned_hits_and_discards_foreign_ids(self):
        """Search returns Odoo chunks only for synced mappings owned by the database."""
        adapter = self._use_adapter(_DatabaseAdapterStub())
        database = self._database("Query Database")
        other_collection, other_chunkset = self._other_collection_with_chunkset("Q")
        other = self._database(
            "Foreign Query Database",
            knowledge_collection_id=other_collection.id,
            chunkset_id=other_chunkset.id,
        )
        _document, chunk = self._chunk()
        _other_document, foreign_chunk = self._chunk(chunkset=other_chunkset)
        database.insert_vectors([[0.1]], metadata=[{"text": "Alpha"}], ids=[chunk.id])
        other.insert_vectors(
            [[0.2]], metadata=[{"text": "Foreign"}], ids=[foreign_chunk.id]
        )
        owned = database.record_ids
        foreign = other.record_ids
        adapter.search_results = [
            {"id": owned.backend_id, "score": 0.9, "payload": {"text": "Alpha"}},
            {"id": foreign.backend_id, "score": 0.99},
            {"id": "unknown-provider-id", "score": 1.0},
        ]

        database.action_initialize()
        results = database.search_vectors([0.1], limit=10)

        self.assertEqual(len(results), 1)
        self.assertEqual(results[0]["id"], chunk.id)
        self.assertEqual(results[0]["backend_id"], owned.backend_id)
        self.assertEqual(results[0]["logical_id"], owned.logical_id)
        self.assertEqual(results[0]["database_id"], database.id)

    def test_query_is_blocked_while_database_is_offline(self):
        """Draft and maintenance databases never expose partial provider data."""
        adapter = self._use_adapter(_DatabaseAdapterStub())
        database = self._database()
        _document, chunk = self._chunk()
        database.insert_vectors([[0.1]], metadata=[{"text": "Alpha"}], ids=[chunk.id])
        adapter.search_results = [
            {"id": database.record_ids.backend_id, "score": 0.9}
        ]

        with self.assertRaises(UserError):
            database.search_vectors([0.1])

        database.action_initialize()
        self.assertEqual(len(database.search_vectors([0.1])), 1)

        database.write({"state": "maintenance"})
        with self.assertRaises(UserError):
            database.search_vectors([0.1])

    def test_document_unlink_cleans_provider_mapping_first(self):
        """Deleting a document removes remote records before chunk pointers cascade."""
        adapter = self._use_adapter(_DatabaseAdapterStub())
        database = self._database()
        document, chunk = self._chunk()
        database.insert_vectors([[0.1]], metadata=[{"text": "Alpha"}], ids=[chunk.id])
        backend_id = database.record_ids.backend_id
        adapter.calls.clear()

        document.unlink()

        self.assertFalse(document.exists())
        self.assertFalse(chunk.exists())
        self.assertFalse(database.record_ids)
        self.assertEqual(adapter.calls[0][0], "delete_records")
        self.assertEqual(adapter.calls[0][3], [backend_id])

    def test_document_cleanup_failure_preserves_ownership(self):
        """A failed delete rolls back locally and keeps the prior mapping for retry."""
        adapter = self._use_adapter(_DatabaseAdapterStub())
        database = self._database()
        document, chunk = self._chunk()
        database.insert_vectors([[0.1]], metadata=[{"text": "Alpha"}], ids=[chunk.id])
        adapter.fail_delete = True

        with self.assertRaises(UserError), self.env.cr.savepoint():
            document.unlink()

        self.assertTrue(document.exists())
        self.assertTrue(chunk.exists())
        self.assertTrue(database.record_ids.exists())
        self.assertEqual(database.record_ids.state, "synced")

    def test_unconfirmed_first_upsert_rolls_back_mapping(self):
        """A failed first write leaves no false local ownership after rollback."""
        adapter = self._use_adapter(_DatabaseAdapterStub())
        adapter.insert_result = False
        database = self._database()
        _document, chunk = self._chunk()

        with self.assertRaises(UserError), self.env.cr.savepoint():
            database.insert_vectors(
                [[0.1]], metadata=[{"text": "Alpha"}], ids=[chunk.id]
            )

        self.assertFalse(database.record_ids)

    def test_collection_only_selects_an_owned_default_database(self):
        """A collection has no store/model shortcuts and selects only its database."""
        database = self._database()
        other_collection, other_chunkset = self._other_collection_with_chunkset("C")
        foreign = self._database(
            "Foreign Default Database",
            knowledge_collection_id=other_collection.id,
            chunkset_id=other_chunkset.id,
        )

        self.assertNotIn("store_id", self.collection._fields)
        self.assertNotIn("embedding_model_id", self.collection._fields)
        self.collection.default_database_id = database
        self.assertEqual(self.collection.default_database_id, database)

        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self.collection.default_database_id = foreign

    def test_chunk_defaults_do_not_create_store_configuration(self):
        """Editing default splitting updates builds but never creates a database."""
        self.assertFalse(self.collection.database_ids)
        self.assertFalse(self.collection.vector_ids)

        self.collection.write({"default_chunk_size": 640})

        self.assertEqual(self.chunkset.splitter_id.chunk_size, 640)
        self.assertEqual(self.chunkset.state, "draft")
        self.assertFalse(self.collection.database_ids)
        self.assertFalse(self.collection.vector_ids)


    def test_database_owns_dense_and_sparse_embedding_roles(self):
        """A database, not its KB, configures dense and sparse model roles."""
        database = self._database(
            sparse_embedding_model_id=self.sparse_embedding_model.id,
            dimension=3,
        )

        self.assertEqual(database.dense_embedding_model_id, self.embedding_model)
        self.assertEqual(
            database.sparse_embedding_model_id, self.sparse_embedding_model
        )
        self.assertEqual(database.dimension, 3)
        self.assertNotIn("dense_embedding_model_id", self.collection._fields)
        self.assertNotIn("sparse_embedding_model_id", self.collection._fields)

    def test_sparse_only_database_has_no_dense_dimension(self):
        """A sparse-only database provisions without a dense vector dimension."""
        self._use_adapter(_DatabaseAdapterStub())
        database = self._database(
            dense_embedding_model_id=False,
            sparse_embedding_model_id=self.sparse_embedding_model.id,
        )

        database.action_initialize()

        self.assertEqual(database.state, "ready")
        self.assertFalse(database.dimension)
        other_collection, other_chunkset = self._other_collection_with_chunkset("S")
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self._database(
                "Invalid Sparse Dimension Database",
                knowledge_collection_id=other_collection.id,
                chunkset_id=other_chunkset.id,
                dense_embedding_model_id=False,
                sparse_embedding_model_id=self.sparse_embedding_model.id,
                dimension=3,
            )

    def test_database_requires_an_embedding_role(self):
        """A vector database cannot omit both dense and sparse embeddings."""
        with self.assertRaises(ValidationError), self.env.cr.savepoint():
            self._database(
                dense_embedding_model_id=False,
                sparse_embedding_model_id=False,
            )

    def test_sparse_vectors_cross_the_database_adapter_contract(self):
        """Sparse-only records use the same persistent provider-ID mapping."""
        adapter = self._use_adapter(_DatabaseAdapterStub())
        database = self._database(
            dense_embedding_model_id=False,
            sparse_embedding_model_id=self.sparse_embedding_model.id,
        )
        _document, chunk = self._chunk()
        sparse = [{"indices": [1, 9], "values": [0.4, 0.8]}]

        database.insert_vectors(
            vectors=None,
            sparse_vectors=sparse,
            metadata=[{"text": "Sparse text"}],
            ids=[chunk.id],
        )

        insert_call = next(call for call in adapter.calls if call[0] == "insert")
        self.assertIsNone(insert_call[3])
        self.assertEqual(insert_call[6], sparse)
        self.assertEqual(database.record_ids.state, "synced")

    def test_synced_provider_id_cannot_be_replaced(self):
        """A later upsert cannot orphan the provider ID already owned by a mapping."""
        adapter = self._use_adapter(_DatabaseAdapterStub())
        database = self._database()
        _document, chunk = self._chunk()
        database.insert_vectors([[0.1]], metadata=[{"text": "Alpha"}], ids=[chunk.id])
        stable_backend_id = database.record_ids.backend_id

        adapter.insert_result = ["provider-record-beta"]
        with self.assertRaises(UserError), self.env.cr.savepoint():
            database.insert_vectors(
                [[0.2]], metadata=[{"text": "Updated"}], ids=[chunk.id]
            )

        self.assertEqual(database.record_ids.backend_id, stable_backend_id)
        self.assertEqual(database.record_ids.state, "synced")

    def test_collection_default_database_scopes_dense_search(self):
        """KB-scoped dense retrieval selects only that KB's default database."""
        first = self._database("Default Retrieval Database")
        alternate_splitter = self.env["llm.knowledge.splitter"].create(
            {
                "name": "Alternate Retrieval Splitter",
                "splitter_type": "recursive",
                "chunk_size": 300,
                "chunk_overlap": 30,
            }
        )
        alternate_chunkset = self.env["llm.knowledge.chunkset"].create(
            {
                "name": "Alternate Retrieval Chunkset",
                "collection_id": self.collection.id,
                "splitter_id": alternate_splitter.id,
            }
        )
        second = self._database(
            "Alternate Retrieval Database", chunkset_id=alternate_chunkset.id
        )
        first_build = first._ensure_vector()
        second_build = second._ensure_vector()
        (first_build | second_build).write({"state": "vectorized"})
        self.collection.default_database_id = first

        selected = self.env["llm.store.chunk"]._get_vector_search_vectors(
            "query",
            None,
            knowledge_collection_id=self.collection.id,
        )

        self.assertEqual(selected, first_build)


    def test_chunkset_cannot_leave_its_database_knowledge_collection(self):
        """Changing the chunkset side cannot break the KB-database ownership chain."""
        database = self._database()
        other_collection, _other_chunkset = self._other_collection_with_chunkset("M")

        with self.assertRaises(UserError), self.env.cr.savepoint():
            self.chunkset.collection_id = other_collection

        self.assertEqual(self.chunkset.collection_id, self.collection)
        self.assertEqual(self.chunkset.database_ids, database)
        self.assertEqual(self.chunkset.database_count, 1)


    def test_insert_enforces_configured_vector_roles_and_dimension(self):
        """The database facade rejects missing roles, ragged vectors, and drift."""
        self._use_adapter(_DatabaseAdapterStub())
        database = self._database(dimension=2)
        _document, chunk = self._chunk()

        with self.assertRaises(UserError):
            database.insert_vectors(
                vectors=None,
                sparse_vectors=[{"indices": [1], "values": [0.5]}],
                metadata=[{"text": "Wrong role"}],
                ids=[chunk.id],
            )
        with self.assertRaises(UserError):
            database.insert_vectors(
                [[0.1, 0.2, 0.3]],
                metadata=[{"text": "Wrong dimension"}],
                ids=[chunk.id],
            )

        second_document, second_chunk = self._chunk()
        with self.assertRaises(UserError):
            database.insert_vectors(
                [[0.1, 0.2], [0.3]],
                metadata=[{"text": "A"}, {"text": "B"}],
                ids=[chunk.id, second_chunk.id],
            )
        self.assertTrue(second_document.exists())

    def test_search_forwards_provider_options(self):
        """Provider-specific search options pass through without lifecycle scope."""
        adapter = self._use_adapter(_DatabaseAdapterStub())
        database = self._database(dimension=1)
        database.action_initialize()

        database.search_vectors([0.1], provider_option="value")

        search_call = next(call for call in adapter.calls if call[0] == "search")
        self.assertEqual(search_call[6]["provider_option"], "value")

    def test_explicit_database_scope_must_match_knowledge_collection(self):
        """Combining DB and KB scopes cannot retrieve a different KB's build."""
        database = self._database()
        build = database._ensure_vector()
        build.state = "vectorized"
        other_collection, _other_chunkset = self._other_collection_with_chunkset("X")

        selected = self.env["llm.store.chunk"]._get_vector_search_vectors(
            "query",
            None,
            database_id=database.id,
            knowledge_collection_id=other_collection.id,
        )

        self.assertFalse(selected)

    def test_provider_mapping_and_uuid_identities_are_server_immutable(self):
        """Direct ORM writes cannot bypass database record ownership identities."""
        self._use_adapter(_DatabaseAdapterStub())
        database = self._database()
        _document, chunk = self._chunk()
        database.insert_vectors([[0.1]], metadata=[{"text": "Alpha"}], ids=[chunk.id])
        record = database.record_ids

        with self.assertRaises(UserError):
            record.write({"backend_id": "tampered"})
        with self.assertRaises(UserError):
            record.unlink()
        with self.assertRaises(UserError):
            database.write({"uuid": "tampered"})
        with self.assertRaises(UserError):
            chunk.write({"uuid": "tampered"})

        self.assertEqual(record.backend_id, database.record_ids.backend_id)
