"""Unit tests for the external pgvector store adapter.

These run without a database and without reaching any PostgreSQL server: the
adapter is a plain class, so it can be instantiated with ``object.__new__``, and
every case below exercises a guard clause that runs *before* a connection is
opened.

The focus is the identifier handling. Table names have to be interpolated into
DDL (Postgres takes no parameter in that position), so they are validated
against a whitelist instead of escaped -- which makes those checks the security
boundary of this adapter and worth pinning down.
"""

from types import SimpleNamespace

from odoo.exceptions import UserError
from odoo.tests.common import BaseCase

from odoo.addons.llm_pgvector.components.pgvector_store_adapter import (
    TABLE_PREFIX,
    PgvectorStoreAdapter,
)


def make_adapter():
    """Build the adapter without the component registry or a database."""
    return object.__new__(PgvectorStoreAdapter)


def make_store(connection_uri="postgresql://u@h:5432/db", api_key=None, name="ext"):
    return SimpleNamespace(name=name, connection_uri=connection_uri, api_key=api_key)


class TestSanitizeCollectionName(BaseCase):
    def setUp(self):
        super().setUp()
        self.adapter = make_adapter()
        self.store = make_store()

    def sanitize(self, name):
        return self.adapter.sanitize_collection_name(self.store, name)

    def test_already_safe(self):
        self.assertEqual(self.sanitize("my_docs"), "my_docs")

    def test_lowercased_and_punctuation_replaced(self):
        self.assertEqual(self.sanitize("My Docs!! v2"), "my_docs_v2")

    def test_repeated_separators_collapse(self):
        self.assertEqual(self.sanitize("a---b___c"), "a_b_c")

    def test_leading_and_trailing_separators_stripped(self):
        self.assertEqual(self.sanitize("__docs__"), "docs")

    def test_leading_digit_gets_a_prefix(self):
        """An identifier cannot start with a digit."""
        self.assertEqual(self.sanitize("2024 reports"), "c_2024_reports")

    def test_length_is_capped(self):
        result = self.sanitize("x" * 200)

        self.assertEqual(len(result), 48)

    def test_empty_after_sanitizing_raises(self):
        for name in ("", "   ", "!!!", "---", None):
            with self.subTest(name=name), self.assertRaises(UserError):
                self.sanitize(name)

    def test_output_always_matches_the_identifier_whitelist(self):
        """Whatever comes in, the result must be a safe identifier."""
        import re

        pattern = re.compile(r"^[a-z][a-z0-9_]*$")
        for name in (
            "My Docs",
            "2024",
            "a-b-c",
            "DROP TABLE users",
            "x';DELETE FROM t;--",
            "配置 collection",
            "a" * 100,
        ):
            with self.subTest(name=name):
                self.assertRegex(self.sanitize(name), pattern)


class TestTableName(BaseCase):
    def setUp(self):
        super().setUp()
        self.adapter = make_adapter()
        self.store = make_store()

    def test_prefix_is_applied(self):
        self.assertEqual(
            self.adapter._table(self.store, "My Docs"),
            f"{TABLE_PREFIX}my_docs",
        )

    def test_injection_attempt_is_neutralised(self):
        table = self.adapter._table(self.store, "t; DROP TABLE users; --")

        self.assertNotIn(";", table)
        self.assertNotIn(" ", table)
        self.assertTrue(table.startswith(TABLE_PREFIX))

    def test_unusable_name_raises_instead_of_building_a_table(self):
        with self.assertRaises(UserError):
            self.adapter._table(self.store, "!!!")


class TestGuardClauses(BaseCase):
    """Every case here must fail or short-circuit before connecting."""

    def setUp(self):
        super().setUp()
        self.adapter = make_adapter()
        self.store = make_store()

    def test_create_collection_requires_a_dimension(self):
        with self.assertRaises(UserError):
            self.adapter.create_collection(self.store, "docs", dimension=None)

    def test_insert_vectors_with_nothing_to_do(self):
        self.assertEqual(
            self.adapter.insert_vectors(self.store, "docs", vectors=[]),
            [],
        )
        self.assertEqual(
            self.adapter.insert_vectors(self.store, "docs", vectors=None),
            [],
        )

    def test_insert_vectors_length_mismatch(self):
        with self.assertRaises(UserError):
            self.adapter.insert_vectors(
                self.store,
                "docs",
                vectors=[[1.0], [2.0]],
                ids=["a"],
            )

    def test_delete_vectors_with_nothing_to_do(self):
        self.assertEqual(self.adapter.delete_vectors(self.store, "docs", []), 0)
        self.assertEqual(self.adapter.delete_vectors(self.store, "docs", None), 0)

    def test_search_rejects_an_unknown_metric(self):
        with self.assertRaises(UserError):
            self.adapter.search_vectors(
                self.store,
                "docs",
                query_vector=[1.0],
                metric="manhattan",
            )

    def test_create_index_rejects_an_unknown_type(self):
        with self.assertRaises(UserError):
            self.adapter.create_index(self.store, "docs", index_type="btree")

    def test_create_index_rejects_an_unknown_metric(self):
        with self.assertRaises(UserError):
            self.adapter.create_index(
                self.store,
                "docs",
                index_type="hnsw",
                metric="manhattan",
            )

    def test_connect_requires_a_connection_uri(self):
        with self.assertRaises(UserError):
            self.adapter._connect(make_store(connection_uri=False))


class TestMetricAndIndexTables(BaseCase):
    """The metric/index whitelists are what keep operators out of f-strings."""

    def setUp(self):
        super().setUp()
        self.adapter = make_adapter()

    def test_distance_operators(self):
        from odoo.addons.llm_pgvector.components.pgvector_store_adapter import (
            DEFAULT_METRIC,
            DISTANCE_OPERATORS,
        )

        self.assertEqual(DISTANCE_OPERATORS["cosine"], "<=>")
        self.assertEqual(DISTANCE_OPERATORS["l2"], "<->")
        self.assertEqual(DISTANCE_OPERATORS["inner_product"], "<#>")
        self.assertIn(DEFAULT_METRIC, DISTANCE_OPERATORS)
