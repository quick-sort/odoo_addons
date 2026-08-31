"""Standalone pgvector instance as an ``llm.store`` service.

Implements the ``llm.store.adapter`` contract for ``service == "pgvector"``,
talking to an *external* PostgreSQL server over its own psycopg2 connection
built from ``store.connection_uri`` and ``store.api_key`` (used as the
password when the URI carries no credentials).

Deliberately independent from Odoo's database:

- no dependency on ``base_pgvector``, so Odoo's own database does not need the
  pgvector extension (which requires a superuser to install);
- no dependency on ``llm_knowledge``, so the coming knowledge rework cannot
  break this adapter;
- ``self.collection.env.cr`` is never touched. Every statement runs on the
  external connection.

Storing embeddings *inside* Odoo's database is the other feature, provided by
``llm_knowledge_pgvector`` under the ``pgvector_local`` service key.

Consistency note: writes here do not take part in the Odoo transaction, so an
Odoo rollback after a successful insert leaves orphan vectors -- the same
property ``llm_qdrant`` has. Payloads therefore carry the Odoo-side record ids,
so a reconciliation pass can find and remove orphans later.
"""

import logging
import re

from odoo import _
from odoo.exceptions import UserError

from odoo.addons.component.core import Component

_logger = logging.getLogger(__name__)

# Collection names become table identifiers, so keep them strictly bounded.
_SAFE_NAME = re.compile(r"^[a-z][a-z0-9_]*$")
TABLE_PREFIX = "llm_vec_"
CONNECT_TIMEOUT = 15

# Distance operators per metric, as exposed by pgvector.
DISTANCE_OPERATORS = {
    "cosine": "<=>",
    "l2": "<->",
    "inner_product": "<#>",
}
DEFAULT_METRIC = "cosine"


class PgvectorStoreAdapter(Component):
    _name = "pgvector.store.adapter"
    _inherit = "llm.store.adapter"
    _usage = "pgvector"

    # ------------------------------------------------------------------
    # Connection
    # ------------------------------------------------------------------

    def _connect(self, store):
        """Open a connection to the external PostgreSQL server.

        The caller owns the connection and must close it; see
        :meth:`_cursor`.
        """
        try:
            import psycopg2
        except ImportError as err:
            raise UserError(
                _(
                    "The 'psycopg2' python package is required for the pgvector "
                    "store. Install it with: pip install psycopg2-binary",
                ),
            ) from err

        if not store.connection_uri:
            raise UserError(
                _(
                    "Store '%(name)s' has no connection URI. Expected a "
                    "PostgreSQL DSN such as "
                    "postgresql://user@host:5432/dbname",
                    name=store.name,
                ),
            )

        kwargs = {"dsn": store.connection_uri, "connect_timeout": CONNECT_TIMEOUT}
        if store.api_key:
            # Keep the password out of the stored URI when possible.
            kwargs["password"] = store.api_key

        return psycopg2.connect(**kwargs)

    def _register_vector(self, connection):
        try:
            from pgvector.psycopg2 import register_vector
        except ImportError as err:
            raise UserError(
                _(
                    "The 'pgvector' python package is required for the pgvector "
                    "store. Install it with: pip install pgvector",
                ),
            ) from err
        register_vector(connection)

    # ------------------------------------------------------------------
    # Naming
    # ------------------------------------------------------------------

    def sanitize_collection_name(self, store, name):
        """Reduce ``name`` to a safe lowercase identifier."""
        sanitized = re.sub(r"[^a-zA-Z0-9_]", "_", (name or "").strip()).lower()
        sanitized = re.sub(r"_{2,}", "_", sanitized).strip("_")
        if not sanitized:
            raise UserError(_("Collection name '%(name)s' is empty once sanitized.", name=name))
        if not sanitized[0].isalpha():
            sanitized = f"c_{sanitized}"
        return sanitized[:48]

    def _table(self, store, collection_id):
        """Map a collection id to its table name, rejecting unsafe input.

        Interpolating an identifier into DDL is unavoidable (Postgres takes no
        parameter there), so the name is validated instead of escaped.
        """
        name = self.sanitize_collection_name(store, str(collection_id))
        if not _SAFE_NAME.match(name):
            raise UserError(_("Unsafe collection name: %(name)s", name=collection_id))
        return f"{TABLE_PREFIX}{name}"

    # ------------------------------------------------------------------
    # Collections
    # ------------------------------------------------------------------

    def create_collection(
        self,
        store,
        collection_id,
        dimension=None,
        metadata=None,
        **kwargs,
    ):
        """Create the backing table, its payload column and an index."""
        if not dimension:
            raise UserError(
                _("A vector dimension is required to create a pgvector collection."),
            )

        table = self._table(store, collection_id)
        connection = self._connect(store)
        try:
            self._register_vector(connection)
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    CREATE TABLE IF NOT EXISTS {table} (
                        id        text PRIMARY KEY,
                        embedding vector({int(dimension)}) NOT NULL,
                        payload   jsonb NOT NULL DEFAULT '{{}}'::jsonb
                    )
                    """,
                )
                cursor.execute(
                    f"CREATE INDEX IF NOT EXISTS {table}_payload_idx "
                    f"ON {table} USING gin (payload)",
                )
            connection.commit()
        finally:
            connection.close()

        return {
            "name": table,
            "dimension": int(dimension),
            "metadata": metadata or {},
        }

    def delete_collection(self, store, collection_id, **kwargs):
        table = self._table(store, collection_id)
        connection = self._connect(store)
        try:
            with connection.cursor() as cursor:
                cursor.execute(f"DROP TABLE IF EXISTS {table}")
            connection.commit()
        finally:
            connection.close()
        return True

    def list_collections(self, store, **kwargs):
        connection = self._connect(store)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT tablename FROM pg_tables "
                    "WHERE schemaname = current_schema() AND tablename LIKE %s",
                    [f"{TABLE_PREFIX}%"],
                )
                return [row[0] for row in cursor.fetchall()]
        finally:
            connection.close()

    def collection_exists(self, store, name, **kwargs):
        table = self._table(store, name)
        connection = self._connect(store)
        try:
            with connection.cursor() as cursor:
                cursor.execute("SELECT to_regclass(%s)", [table])
                return cursor.fetchone()[0] is not None
        finally:
            connection.close()

    # ------------------------------------------------------------------
    # Vectors
    # ------------------------------------------------------------------

    def insert_vectors(
        self,
        store,
        collection_id,
        vectors,
        metadata=None,
        ids=None,
        **kwargs,
    ):
        """Upsert vectors with their payload.

        ``metadata`` entries should carry the Odoo-side ids, so orphans left by
        a rolled-back Odoo transaction can be reconciled later.
        """
        table = self._table(store, collection_id)
        vectors = list(vectors or [])
        if not vectors:
            return []

        payloads = list(metadata or [{}] * len(vectors))
        keys = list(ids or range(len(vectors)))
        if not (len(payloads) == len(keys) == len(vectors)):
            raise UserError(
                _("vectors, ids and metadata must have the same length."),
            )

        import json

        connection = self._connect(store)
        try:
            self._register_vector(connection)
            with connection.cursor() as cursor:
                cursor.executemany(
                    f"""
                    INSERT INTO {table} (id, embedding, payload)
                    VALUES (%s, %s, %s)
                    ON CONFLICT (id) DO UPDATE
                        SET embedding = EXCLUDED.embedding,
                            payload   = EXCLUDED.payload
                    """,
                    [
                        (str(key), list(vector), json.dumps(payload or {}))
                        for key, vector, payload in zip(keys, vectors, payloads)
                    ],
                )
            connection.commit()
        finally:
            connection.close()

        return [str(key) for key in keys]

    def delete_vectors(self, store, collection_id, ids, **kwargs):
        table = self._table(store, collection_id)
        ids = [str(i) for i in (ids or [])]
        if not ids:
            return 0

        connection = self._connect(store)
        try:
            with connection.cursor() as cursor:
                cursor.execute(f"DELETE FROM {table} WHERE id = ANY(%s)", [ids])
                deleted = cursor.rowcount
            connection.commit()
        finally:
            connection.close()
        return deleted

    def search_vectors(
        self,
        store,
        collection_id,
        query_vector,
        limit=10,
        filters=None,
        **kwargs,
    ):
        """Nearest-neighbour search, optionally narrowed by a payload filter.

        ``filters`` is matched with the jsonb containment operator, so it is
        passed as a parameter rather than interpolated.
        """
        table = self._table(store, collection_id)
        metric = kwargs.get("metric", DEFAULT_METRIC)
        operator = DISTANCE_OPERATORS.get(metric)
        if not operator:
            raise UserError(
                _(
                    "Unknown distance metric '%(metric)s'. Expected one of: %(known)s",
                    metric=metric,
                    known=", ".join(sorted(DISTANCE_OPERATORS)),
                ),
            )

        import json

        where, params = "", [list(query_vector)]
        if filters:
            where = "WHERE payload @> %s"
            params.append(json.dumps(filters))
        params.append(int(limit))

        connection = self._connect(store)
        try:
            self._register_vector(connection)
            with connection.cursor() as cursor:
                cursor.execute(
                    f"""
                    SELECT id, payload, embedding {operator} %s AS distance
                      FROM {table}
                      {where}
                     ORDER BY distance
                     LIMIT %s
                    """,
                    params,
                )
                return [
                    {"id": row[0], "payload": row[1], "distance": row[2]}
                    for row in cursor.fetchall()
                ]
        finally:
            connection.close()

    # ------------------------------------------------------------------
    # Indexes
    # ------------------------------------------------------------------

    def create_index(self, store, collection_id, index_type=None, **kwargs):
        """Build an approximate-nearest-neighbour index.

        ``hnsw`` is the default: it needs no training pass, unlike ``ivfflat``
        which wants representative data to be present before it is built.
        """
        table = self._table(store, collection_id)
        index_type = (index_type or "hnsw").lower()
        if index_type not in ("hnsw", "ivfflat"):
            raise UserError(
                _("Unknown index type '%(kind)s'. Expected hnsw or ivfflat.", kind=index_type),
            )

        metric = kwargs.get("metric", DEFAULT_METRIC)
        opclass = {
            "cosine": "vector_cosine_ops",
            "l2": "vector_l2_ops",
            "inner_product": "vector_ip_ops",
        }.get(metric)
        if not opclass:
            raise UserError(_("Unknown distance metric '%(metric)s'.", metric=metric))

        index_name = f"{table}_{index_type}_idx"
        if index_type == "ivfflat":
            lists = int(kwargs.get("lists", 100))
            using = f"ivfflat (embedding {opclass}) WITH (lists = {lists})"
        else:
            m = int(kwargs.get("m", 16))
            ef = int(kwargs.get("ef_construction", 64))
            using = (
                f"hnsw (embedding {opclass}) "
                f"WITH (m = {m}, ef_construction = {ef})"
            )

        connection = self._connect(store)
        try:
            self._register_vector(connection)
            with connection.cursor() as cursor:
                cursor.execute(
                    f"CREATE INDEX IF NOT EXISTS {index_name} ON {table} USING {using}",
                )
            connection.commit()
        finally:
            connection.close()

        return {"index": index_name, "type": index_type, "metric": metric}

    # ------------------------------------------------------------------
    # Connectivity
    # ------------------------------------------------------------------

    def validate_config(self, store):
        """Check the server is reachable and has the pgvector extension."""
        connection = self._connect(store)
        try:
            with connection.cursor() as cursor:
                cursor.execute(
                    "SELECT installed_version FROM pg_available_extensions "
                    "WHERE name = 'vector'",
                )
                row = cursor.fetchone()
            if not row:
                raise UserError(
                    _("The target server does not provide the pgvector extension."),
                )
            if not row[0]:
                raise UserError(
                    _(
                        "pgvector is available on the target server but not "
                        "created in this database. Run: CREATE EXTENSION vector",
                    ),
                )
            return {"pgvector_version": row[0]}
        finally:
            connection.close()
