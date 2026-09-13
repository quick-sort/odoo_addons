"""ParadeDB pg_search capability."""

import json

from odoo import _
from odoo.exceptions import UserError

from odoo.addons.component.core import Component


class PgSearchCapability(Component):
    _name = "llm.pg.capability.pg_search"
    _inherit = "llm.pg.capability.adapter"
    _usage = "pg_search"

    def required_extensions(self, store, database, capability):
        return ("pg_search",)

    def probe_runtime(self, store, database, capability, cursor):
        cursor.execute("SELECT EXISTS (SELECT 1 FROM pg_am WHERE amname = 'paradedb')")
        ready = bool(cursor.fetchone()[0])
        return {
            "ready": ready,
            "access_method": "paradedb" if ready else None,
            "error": None if ready else "paradedb index access method is unavailable",
        }

    def supports_query(self, mode):
        return mode == "bm25"

    def create_indexes(
        self,
        store,
        database,
        capability,
        cursor,
        schema_name,
        table_name,
        index_type=None,
        **kwargs,
    ):
        from psycopg2 import sql

        index_name = "records_pg_search_idx"
        cursor.execute(
            sql.SQL(
                "CREATE INDEX IF NOT EXISTS {} ON {}.{} "
                "USING paradedb (id, content, generation, payload) "
                "WITH (key_field = 'id')"
            ).format(
                sql.Identifier(index_name),
                sql.Identifier(schema_name),
                sql.Identifier(table_name),
            )
        )
        return [{"name": index_name, "type": "paradedb"}]

    def search(
        self,
        store,
        database,
        capability,
        cursor,
        schema_name,
        table_name,
        query_vector=None,
        limit=10,
        filter=None,
        **kwargs,
    ):
        from psycopg2 import sql

        query_text = kwargs.get("query_text")
        if not query_text:
            raise UserError(_("pg_search requires query_text."))
        where = [sql.SQL("generation = %s"), sql.SQL("content @@@ %s")]
        parameters = [
            kwargs.get("generation") or database.active_generation,
            query_text,
        ]
        if filter:
            where.append(sql.SQL("payload @> %s::jsonb"))
            parameters.append(json.dumps(filter))
        parameters.append(int(limit))
        cursor.execute(
            sql.SQL(
                "SELECT id, payload, pdb.score(id) AS score "
                "FROM {}.{} WHERE {} ORDER BY score DESC, id LIMIT %s"
            ).format(
                sql.Identifier(schema_name),
                sql.Identifier(table_name),
                sql.SQL(" AND ").join(where),
            ),
            parameters,
        )
        return [
            {"id": record_id, "payload": payload, "score": float(score)}
            for record_id, payload, score in cursor.fetchall()
        ]
