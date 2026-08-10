# Copyright 2026 Rui
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

"""pgvector vector store: a table per index in an external PostgreSQL
instance. Vectors use cosine distance; the payload is stored as jsonb.
"""

import json
import logging
import re

from odoo import _
from odoo.exceptions import UserError

from odoo.addons.component.core import Component

_logger = logging.getLogger(__name__)

_TABLE_RE = re.compile(r"^[a-z0-9_]+$")


class PgvectorStore(Component):
    _name = "pgvector.store"
    _inherit = "knowledge.vector.store.component"
    _usage = "pgvector"

    def _table(self, index_name):
        if not _TABLE_RE.match(index_name):
            raise UserError(_("Invalid table name: %s", index_name))
        return "kvs_" + index_name

    def _connect(self):
        try:
            import psycopg2
        except ImportError as err:
            raise UserError(
                _(
                    "The 'psycopg2' python package is required for the "
                    "pgvector store. Install it with: pip install psycopg2-binary"
                )
            ) from err
        return psycopg2.connect(
            host=self.collection.host,
            port=self.collection.port or 5432,
            dbname=self.collection.database,
            user=self.collection.username,
            password=self.collection.password,
            connect_timeout=15,
        )

    def _register_vector(self, conn):
        try:
            from pgvector.psycopg2 import register_vector
        except ImportError as err:
            raise UserError(
                _(
                    "The 'pgvector' python package is required for the "
                    "pgvector store. Install it with: pip install pgvector"
                )
            ) from err
        register_vector(conn)

    def ensure_index(self, index_name, vector_size):
        table = self._table(index_name)
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                self._register_vector(conn)
                cur.execute("SELECT to_regclass(%s)", (table,))
                if cur.fetchone()[0] is None:
                    cur.execute(
                        "CREATE TABLE %s ("
                        "id text PRIMARY KEY, "
                        "vector vector(%s), "
                        "payload jsonb"
                        ")" % (table, int(vector_size))
                    )
                    cur.execute(
                        "CREATE INDEX ON %s USING hnsw (vector vector_cosine_ops)"
                        % table
                    )
            conn.commit()
        finally:
            conn.close()

    def upsert(self, index_name, points):
        table = self._table(index_name)
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                self._register_vector(conn)
                for point_id, vector, payload in points:
                    cur.execute(
                        "INSERT INTO %s (id, vector, payload) VALUES (%%s, %%s, %%s) "
                        "ON CONFLICT (id) DO UPDATE SET vector = EXCLUDED.vector, "
                        "payload = EXCLUDED.payload" % table,
                        (point_id, vector, json.dumps(payload)),
                    )
            conn.commit()
        finally:
            conn.close()

    def search(self, index_name, vector, limit=10, filters=None):
        table = self._table(index_name)
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                self._register_vector(conn)
                cur.execute(
                    "SELECT id, payload, 1 - (vector <=> %%s) AS score "
                    "FROM %s WHERE vector IS NOT NULL "
                    "ORDER BY vector <=> %%s LIMIT %%s" % table,
                    (vector, vector, int(limit)),
                )
                rows = cur.fetchall()
        finally:
            conn.close()
        results = []
        for row_id, payload, score in rows:
            data = payload if isinstance(payload, dict) else {}
            results.append(
                {"id": row_id, "score": score, "payload": data}
            )
        return results

    def drop_index(self, index_name):
        table = self._table(index_name)
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute("DROP TABLE IF EXISTS %s" % table)
            conn.commit()
        finally:
            conn.close()

    def validate_config(self):
        conn = self._connect()
        try:
            with conn.cursor() as cur:
                cur.execute("SELECT 1")
                cur.fetchone()
        finally:
            conn.close()
