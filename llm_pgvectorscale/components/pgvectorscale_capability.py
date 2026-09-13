"""pgvectorscale StreamingDiskANN index capability."""

from odoo import _
from odoo.exceptions import UserError

from odoo.addons.component.core import Component

OPCLASSES = {
    "cosine": "vector_cosine_ops",
    "l2": "vector_l2_ops",
    "inner_product": "vector_ip_ops",
}


class PgvectorScaleCapability(Component):
    _name = "llm.pg.capability.pgvectorscale"
    _inherit = "llm.pg.capability.adapter"
    _usage = "pgvectorscale"

    def _config(self, database, capability):
        config = dict((database.index_configuration or {}).get("pgvectorscale") or {})
        config.update(capability.configuration or {})
        return config

    def required_extensions(self, store, database, capability):
        return ("vectorscale",)

    def probe_runtime(self, store, database, capability, cursor):
        cursor.execute("SELECT EXISTS (SELECT 1 FROM pg_am WHERE amname = 'diskann')")
        ready = bool(cursor.fetchone()[0])
        return {
            "ready": ready,
            "access_method": "diskann" if ready else None,
            "error": None if ready else "diskann index access method is unavailable",
        }

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

        if not database.dense_embedding_model_id:
            raise UserError(_("pgvectorscale requires a dense embedding column."))
        config = self._config(database, capability)
        metric = config.get("metric", "cosine")
        opclass = OPCLASSES.get(metric)
        if not opclass:
            raise UserError(_("Unsupported pgvectorscale metric '%s'.", metric))
        num_neighbors = max(10, int(config.get("num_neighbors", 50)))
        index_name = "records_embedding_diskann_idx"
        cursor.execute(
            sql.SQL(
                "CREATE INDEX IF NOT EXISTS {} ON {}.{} USING diskann "
                "(embedding {}) WITH (num_neighbors = {})"
            ).format(
                sql.Identifier(index_name),
                sql.Identifier(schema_name),
                sql.Identifier(table_name),
                sql.SQL(opclass),
                sql.SQL(str(num_neighbors)),
            )
        )
        return [
            {
                "name": index_name,
                "type": "diskann",
                "metric": metric,
                "num_neighbors": num_neighbors,
            }
        ]
