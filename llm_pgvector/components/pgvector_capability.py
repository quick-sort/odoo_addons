"""pgvector capability for the PostgreSQL control plane."""

from odoo import _
from odoo.exceptions import UserError

from odoo.addons.component.core import Component

DISTANCE = {
    "cosine": ("<=>", "vector_cosine_ops"),
    "l2": ("<->", "vector_l2_ops"),
    "inner_product": ("<#>", "vector_ip_ops"),
}


class PgvectorCapability(Component):
    _name = "llm.pg.capability.pgvector"
    _inherit = "llm.pg.capability.adapter"
    _usage = "pgvector"

    def _config(self, database, capability):
        config = dict((database.index_configuration or {}).get("pgvector") or {})
        config.update(capability.configuration or {})
        return config

    def required_extensions(self, store, database, capability):
        return ("vector",)

    def probe_runtime(self, store, database, capability, cursor):
        cursor.execute(
            "SELECT to_regtype('vector')::text, to_regtype('sparsevec')::text"
        )
        vector_type, sparse_type = cursor.fetchone()
        if not vector_type:
            return {"ready": False, "error": "vector type is not registered"}
        if database.sparse_embedding_model_id and not sparse_type:
            return {
                "ready": False,
                "error": "sparsevec is unavailable in the installed vector extension",
            }
        return {
            "ready": True,
            "dense": bool(vector_type),
            "sparse": bool(sparse_type),
        }

    def provision_schema(
        self, store, database, capability, cursor, schema_name, table_name
    ):
        from psycopg2 import sql

        if database.dense_embedding_model_id:
            if not database.dimension:
                raise UserError(_("Dense pgvector storage requires a dimension."))
            cursor.execute(
                sql.SQL(
                    "ALTER TABLE {}.{} ADD COLUMN IF NOT EXISTS {} vector({})"
                ).format(
                    sql.Identifier(schema_name),
                    sql.Identifier(table_name),
                    sql.Identifier("embedding"),
                    sql.SQL(str(int(database.dimension))),
                )
            )
        if database.sparse_embedding_model_id:
            config = self._config(database, capability)
            sparse_dimension = int(config.get("sparse_dimension") or 0)
            if sparse_dimension <= 0:
                raise UserError(
                    _("Sparse pgvector storage requires configuration.sparse_dimension.")
                )
            cursor.execute(
                sql.SQL(
                    "ALTER TABLE {}.{} ADD COLUMN IF NOT EXISTS {} sparsevec({})"
                ).format(
                    sql.Identifier(schema_name),
                    sql.Identifier(table_name),
                    sql.Identifier("sparse_embedding"),
                    sql.SQL(str(sparse_dimension)),
                )
            )
        return True

    @staticmethod
    def _dense_literal(vector):
        return "[" + ",".join(str(float(value)) for value in vector) + "]"

    def _sparse_literal(self, vector, dimension, zero_based):
        if isinstance(vector, str):
            return vector
        if isinstance(vector, dict) and "indices" in vector and "values" in vector:
            pairs = zip(vector["indices"], vector["values"], strict=True)
        elif isinstance(vector, dict):
            pairs = vector.items()
        else:
            try:
                pairs = vector
            except TypeError as error:
                raise UserError(_("Unsupported sparse vector representation.")) from error
        normalized = []
        for index, value in pairs:
            index = int(index) + (1 if zero_based else 0)
            if index <= 0 or index > dimension:
                raise UserError(
                    _("Sparse vector index %(index)s exceeds dimension %(dimension)s.", index=index, dimension=dimension)
                )
            normalized.append((index, float(value)))
        normalized.sort(key=lambda item: item[0])
        body = ",".join(f"{index}:{value}" for index, value in normalized)
        return f"{{{body}}}/{dimension}"

    def prepare_upsert(
        self,
        store,
        database,
        capability,
        vectors=None,
        sparse_vectors=None,
        metadata=None,
        ids=None,
    ):
        config = self._config(database, capability)
        columns = []
        column_values = []
        count = len(ids or [])
        if vectors is not None:
            columns.append("embedding")
            column_values.append([self._dense_literal(vector) for vector in vectors])
        if sparse_vectors is not None:
            dimension = int(config.get("sparse_dimension") or 0)
            if dimension <= 0:
                raise UserError(_("Sparse vector writes require sparse_dimension."))
            zero_based = bool(config.get("sparse_indices_zero_based", True))
            columns.append("sparse_embedding")
            column_values.append(
                [
                    self._sparse_literal(vector, dimension, zero_based)
                    for vector in sparse_vectors
                ]
            )
        if not columns:
            return None
        return {
            "columns": columns,
            "values": [
                [values[row_index] for values in column_values]
                for row_index in range(count)
            ],
        }

    def supports_query(self, mode):
        return mode in ("dense", "sparse")

    def _metric(self, config, sparse=False):
        default = "inner_product" if sparse else "cosine"
        metric = config.get("sparse_metric" if sparse else "dense_metric", default)
        if metric not in DISTANCE:
            raise UserError(_("Unsupported pgvector metric '%s'.", metric))
        return metric, DISTANCE[metric]

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
        import json

        from psycopg2 import sql

        mode = kwargs.get("query_mode") or "dense"
        sparse = mode == "sparse"
        config = self._config(database, capability)
        metric, (operator, _opclass) = self._metric(config, sparse=sparse)
        vector = kwargs.get("sparse_query_vector") if sparse else query_vector
        if vector is None:
            raise UserError(_("The pgvector query vector is missing."))
        if sparse:
            dimension = int(config.get("sparse_dimension") or 0)
            vector = self._sparse_literal(
                vector,
                dimension,
                bool(config.get("sparse_indices_zero_based", True)),
            )
            column = "sparse_embedding"
            cast = "sparsevec"
        else:
            vector = self._dense_literal(vector)
            column = "embedding"
            cast = "vector"

        where = [sql.SQL("generation = %s")]
        where_parameters = [kwargs.get("generation") or database.active_generation]
        if filter:
            where.append(sql.SQL("payload @> %s::jsonb"))
            where_parameters.append(json.dumps(filter))
        distance_expression = sql.SQL("{} {} %s::{}").format(
            sql.Identifier(column), sql.SQL(operator), sql.SQL(cast)
        )
        parameters = [vector, *where_parameters, int(limit)]
        statement = sql.SQL(
            "SELECT id, payload, {distance} AS distance FROM {schema}.{table} "
            "WHERE {where} ORDER BY distance LIMIT %s"
        ).format(
            distance=distance_expression,
            schema=sql.Identifier(schema_name),
            table=sql.Identifier(table_name),
            where=sql.SQL(" AND ").join(where),
        )
        cursor.execute(statement, parameters)
        results = []
        for record_id, payload, distance in cursor.fetchall():
            distance = float(distance)
            if metric == "cosine":
                score = 1.0 - distance
            elif metric == "inner_product":
                score = -distance
            else:
                score = 1.0 / (1.0 + max(distance, 0.0))
            results.append(
                {
                    "id": record_id,
                    "payload": payload,
                    "score": score,
                    "distance": distance,
                }
            )
        return results

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
        created = []
        if database.dense_embedding_model_id:
            kind = index_type or config.get("dense_index", "hnsw")
            if kind != "none":
                metric, (_operator, opclass) = self._metric(config)
                created.append(
                    self._create_vector_index(
                        cursor,
                        schema_name,
                        table_name,
                        "embedding",
                        "records_embedding_idx",
                        kind,
                        opclass,
                        config,
                    )
                )
        if database.sparse_embedding_model_id:
            kind = config.get("sparse_index", "hnsw")
            if kind != "none":
                if kind != "hnsw":
                    raise UserError(_("Sparse pgvector indexes currently require HNSW."))
                created.append(
                    self._create_vector_index(
                        cursor,
                        schema_name,
                        table_name,
                        "sparse_embedding",
                        "records_sparse_embedding_idx",
                        kind,
                        "sparsevec_ip_ops",
                        config,
                    )
                )
        return created

    def _create_vector_index(
        self,
        cursor,
        schema_name,
        table_name,
        column_name,
        index_name,
        kind,
        opclass,
        config,
    ):
        from psycopg2 import sql

        if kind not in ("hnsw", "ivfflat"):
            raise UserError(_("Unsupported pgvector index '%s'.", kind))
        if kind == "hnsw":
            m = max(2, int(config.get("m", 16)))
            ef = max(4, int(config.get("ef_construction", 64)))
            options = sql.SQL(" WITH (m = {}, ef_construction = {})").format(
                sql.SQL(str(m)), sql.SQL(str(ef))
            )
        else:
            lists = max(1, int(config.get("lists", 100)))
            options = sql.SQL(" WITH (lists = {})").format(sql.SQL(str(lists)))
        cursor.execute(
            sql.SQL(
                "CREATE INDEX IF NOT EXISTS {} ON {}.{} USING {} ({} {}){}"
            ).format(
                sql.Identifier(index_name),
                sql.Identifier(schema_name),
                sql.Identifier(table_name),
                sql.SQL(kind),
                sql.Identifier(column_name),
                sql.SQL(opclass),
                options,
            )
        )
        return {"name": index_name, "type": kind, "opclass": opclass}
