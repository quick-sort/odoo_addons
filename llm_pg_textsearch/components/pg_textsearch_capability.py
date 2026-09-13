"""Timescale/Tiger Data pg_textsearch capability."""

import json

from odoo import _
from odoo.exceptions import UserError

from odoo.addons.component.core import Component


class PgTextSearchCapability(Component):
    _name = "llm.pg.capability.pg_textsearch"
    _inherit = "llm.pg.capability.adapter"
    _usage = "pg_textsearch"

    def _config(self, database, capability):
        config = dict((database.index_configuration or {}).get("pg_textsearch") or {})
        config.update(capability.configuration or {})
        return config

    def required_extensions(self, store, database, capability):
        return ("pg_textsearch",)

    def probe_runtime(self, store, database, capability, cursor):
        cursor.execute("SELECT EXISTS (SELECT 1 FROM pg_am WHERE amname = 'bm25')")
        ready = bool(cursor.fetchone()[0])
        return {
            "ready": ready,
            "access_method": "bm25" if ready else None,
            "error": None if ready else "bm25 index access method is unavailable",
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

        config = self._config(database, capability)
        text_config = config.get("text_config", "simple")
        index_name = "records_pg_textsearch_idx"
        cursor.execute(
            sql.SQL(
                "CREATE INDEX IF NOT EXISTS {} ON {}.{} USING bm25 (content) "
                "WITH (text_config = {})"
            ).format(
                sql.Identifier(index_name),
                sql.Identifier(schema_name),
                sql.Identifier(table_name),
                sql.Literal(text_config),
            )
        )
        return [
            {"name": index_name, "type": "bm25", "text_config": text_config}
        ]

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
            raise UserError(_("pg_textsearch requires query_text."))
        where = [sql.SQL("generation = %s")]
        parameters = [query_text, kwargs.get("generation") or database.active_generation]
        if filter:
            where.append(sql.SQL("payload @> %s::jsonb"))
            parameters.append(json.dumps(filter))
        parameters.append(int(limit))
        cursor.execute(
            sql.SQL(
                "SELECT id, payload, content <@> %s AS distance "
                "FROM {}.{} WHERE {} ORDER BY distance ASC, id LIMIT %s"
            ).format(
                sql.Identifier(schema_name),
                sql.Identifier(table_name),
                sql.SQL(" AND ").join(where),
            ),
            parameters,
        )
        return [
            {
                "id": record_id,
                "payload": payload,
                "score": -float(distance),
                "distance": float(distance),
            }
            for record_id, payload, distance in cursor.fetchall()
        ]
