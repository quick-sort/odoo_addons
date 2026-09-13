"""Qdrant implementation of the database-scoped ``llm.store`` contract."""

import base64
import hashlib
import hmac
import json
import logging
import re
import uuid
from datetime import timedelta, timezone

from qdrant_client import QdrantClient
from qdrant_client import models as qdrant_models
from qdrant_client.http.exceptions import UnexpectedResponse

from odoo import _
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Datetime

from odoo.addons.component.core import Component

_logger = logging.getLogger(__name__)

DEFAULT_HOST = "localhost"
DEFAULT_PORT = 6333
DELETE_TIMEOUT = 30
DEFAULT_DENSE_VECTOR = "dense"
DEFAULT_SPARSE_VECTOR = "sparse"

_PAYLOAD_SCHEMA_NAMES = {
    "keyword": "KEYWORD",
    "integer": "INTEGER",
    "float": "FLOAT",
    "geo": "GEO",
    "text": "TEXT",
    "bool": "BOOL",
    "datetime": "DATETIME",
    "uuid": "UUID",
}

_DISTANCE_NAMES = {
    "cosine": qdrant_models.Distance.COSINE,
    "dot": qdrant_models.Distance.DOT,
    "euclid": qdrant_models.Distance.EUCLID,
    "euclidean": qdrant_models.Distance.EUCLID,
    "manhattan": qdrant_models.Distance.MANHATTAN,
}


class QdrantStoreAdapter(Component):
    _name = "qdrant.store.adapter"
    _inherit = "llm.store.adapter"
    _usage = "qdrant"

    # ------------------------------------------------------------------
    # Client and provider identity
    # ------------------------------------------------------------------
    def _client(self, store):
        kwargs = {}
        if store.connection_uri:
            kwargs["url"] = store.connection_uri
        else:
            kwargs.update(host=DEFAULT_HOST, port=DEFAULT_PORT)
        if store.api_key:
            kwargs["api_key"] = store.api_key
        try:
            return QdrantClient(**kwargs)
        except Exception as error:  # noqa: BLE001
            raise UserError(
                _(
                    "Could not initialize the Qdrant client for '%(store)s': "
                    "%(error)s",
                    store=store.name,
                    error=error,
                )
            ) from error

    @staticmethod
    def _sanitize_name(name):
        value = re.sub(r"[^a-zA-Z0-9._-]+", "-", str(name or "").strip())
        value = re.sub(r"[-_.]{2,}", "-", value).strip("-_.")
        return value[:200] or "odoo-vectors"

    def _database_name(self, store, database, persist=False):
        name = database.database_name or self._sanitize_name(
            f"odoo-{store.env.cr.dbname}-{database.uuid}"
        )
        if persist and not database.database_name:
            database.with_context(allow_provider_resource_write=True).write(
                {"database_name": name}
            )
        return name

    @staticmethod
    def _configuration(database):
        return dict(database.index_configuration or {})

    def _dense_vector_name(self, database):
        return self._configuration(database).get(
            "dense_vector_name", DEFAULT_DENSE_VECTOR
        )

    def _sparse_vector_name(self, database):
        return self._configuration(database).get(
            "sparse_vector_name", DEFAULT_SPARSE_VECTOR
        )

    @staticmethod
    def _ensure_dedicated(database):
        if database.isolation_mode != "database":
            raise UserError(
                _(
                    "Qdrant currently requires dedicated provider resources for "
                    "database '%s'. Shared namespace/tenant resources cannot be "
                    "safely granted to direct clients.",
                    database.name,
                )
            )

    @staticmethod
    def _collection_metadata_from_info(info):
        return dict(getattr(getattr(info, "config", None), "metadata", None) or {})

    def _assert_collection_owner(self, client, name, database):
        metadata = self._collection_metadata_from_info(
            client.get_collection(collection_name=name)
        )
        if (
            metadata.get("managed_by") != "odoo"
            or metadata.get("resource_type") != "llm.store.database"
            or metadata.get("store_instance_uuid")
            != database.store_id.qdrant_instance_uuid
            or metadata.get("database_uuid") != database.uuid
        ):
            raise UserError(
                _(
                    "Qdrant collection '%(collection)s' is not owned by database "
                    "'%(database)s'. Choose a unique collection name instead of "
                    "adopting or deleting an unrelated collection.",
                    collection=name,
                    database=database.name,
                )
            )
        return True

    def _assert_registry_owner(self, client, name, store):
        metadata = self._collection_metadata_from_info(
            client.get_collection(collection_name=name)
        )
        if (
            metadata.get("managed_by") != "odoo"
            or metadata.get("resource_type") != "qdrant.credential.registry"
            or metadata.get("store_instance_uuid") != store.qdrant_instance_uuid
        ):
            raise UserError(
                _(
                    "Qdrant collection '%s' is not this store's credential "
                    "registry. Configure a unique registry collection name.",
                    name,
                )
            )
        return True

    # ------------------------------------------------------------------
    # Collection schema
    # ------------------------------------------------------------------
    @staticmethod
    def _memory(value):
        if not value:
            return None
        enum = getattr(qdrant_models, "Memory", None)
        if not enum:
            return None
        return getattr(enum, str(value).upper(), None)

    @staticmethod
    def _datatype(value):
        if not value:
            return None
        enum = getattr(qdrant_models, "Datatype", None)
        if not enum:
            return None
        return getattr(enum, str(value).upper(), None)

    def _dense_config(self, database):
        config = self._configuration(database)
        if not database.dense_embedding_model_id:
            return None
        if not database.dimension:
            raise UserError(
                _("Set the dense dimension before provisioning '%s'.", database.name)
            )
        distance_name = str(config.get("distance", "cosine")).lower()
        distance = _DISTANCE_NAMES.get(distance_name)
        if not distance:
            raise UserError(_("Unsupported Qdrant distance '%s'.", distance_name))

        values = {"size": database.dimension, "distance": distance}
        memory = self._memory(config.get("vector_memory"))
        datatype = self._datatype(config.get("datatype"))
        if memory is not None:
            values["memory"] = memory
        if datatype is not None:
            values["datatype"] = datatype
        if config.get("vector_hnsw_config"):
            values["hnsw_config"] = qdrant_models.HnswConfigDiff(
                **config["vector_hnsw_config"]
            )
        if config.get("vector_quantization_config"):
            values["quantization_config"] = self._quantization(
                config["vector_quantization_config"]
            )
        return qdrant_models.VectorParams(**values)

    def _sparse_config(self, database):
        if not database.sparse_embedding_model_id:
            return None
        config = self._configuration(database)
        values = {}
        sparse_index = config.get("sparse_index_config")
        if sparse_index:
            values["index"] = qdrant_models.SparseIndexParams(**sparse_index)
        modifier = str(config.get("sparse_modifier", "idf")).lower()
        if modifier == "idf":
            values["modifier"] = qdrant_models.Modifier.IDF
        elif modifier not in ("", "none"):
            raise UserError(_("Unsupported Qdrant sparse modifier '%s'.", modifier))
        return qdrant_models.SparseVectorParams(**values)

    @staticmethod
    def _model(model_name, value):
        if not value:
            return None
        model = getattr(qdrant_models, model_name, None)
        return model(**value) if model else value

    @staticmethod
    def _quantization(value):
        if not value:
            return None
        if "scalar" in value:
            return qdrant_models.ScalarQuantization(
                scalar=qdrant_models.ScalarQuantizationConfig(**value["scalar"])
            )
        if "product" in value:
            return qdrant_models.ProductQuantization(
                product=qdrant_models.ProductQuantizationConfig(**value["product"])
            )
        if "binary" in value:
            return qdrant_models.BinaryQuantization(
                binary=qdrant_models.BinaryQuantizationConfig(**value["binary"])
            )
        raise UserError(
            _("Qdrant quantization must define scalar, product, or binary settings.")
        )

    def _collection_metadata(self, store, database):
        return {
            "managed_by": "odoo",
            "resource_type": "llm.store.database",
            "schema_version": 1,
            "store_uuid": store.env.cr.dbname,
            "store_instance_uuid": store.qdrant_instance_uuid,
            "database_uuid": database.uuid,
            "knowledge_collection_id": database.knowledge_collection_id.id,
            "text_field": "text",
            "dense_vector": (
                self._dense_vector_name(database)
                if database.dense_embedding_model_id
                else None
            ),
            "sparse_vector": (
                self._sparse_vector_name(database)
                if database.sparse_embedding_model_id
                else None
            ),
        }

    def _create_collection_kwargs(self, store, database):
        config = self._configuration(database)
        dense = self._dense_config(database)
        sparse = self._sparse_config(database)
        values = {
            "vectors_config": (
                {self._dense_vector_name(database): dense} if dense else {}
            ),
            "sparse_vectors_config": (
                {self._sparse_vector_name(database): sparse} if sparse else None
            ),
            "shard_number": config.get("shard_number"),
            "replication_factor": config.get("replication_factor"),
            "write_consistency_factor": config.get("write_consistency_factor"),
            "hnsw_config": self._model("HnswConfigDiff", config.get("hnsw_config")),
            "optimizers_config": self._model(
                "OptimizersConfigDiff", config.get("optimizers_config")
            ),
            "wal_config": self._model("WalConfigDiff", config.get("wal_config")),
            "quantization_config": self._quantization(
                config.get("quantization_config")
            ),
            "strict_mode_config": self._model(
                "StrictModeConfig", config.get("strict_mode_config")
            ),
            "payload": self._model(
                "PayloadStorageParams", config.get("payload_config")
            ),
            "metadata": self._collection_metadata(store, database),
        }
        sharding_method = config.get("sharding_method")
        if sharding_method:
            values["sharding_method"] = getattr(
                qdrant_models.ShardingMethod, str(sharding_method).upper()
            )
        return {key: value for key, value in values.items() if value is not None}

    # ------------------------------------------------------------------
    # Required database contract
    # ------------------------------------------------------------------
    def database_exists(self, store, database, **kwargs):
        self._ensure_dedicated(database)
        client = self._client(store)
        name = self._database_name(store, database)
        exists = client.collection_exists(collection_name=name)
        if exists:
            self._assert_collection_owner(client, name, database)
        return exists

    def provision_database(self, store, database, **kwargs):
        self._ensure_dedicated(database)
        client = self._client(store)
        name = self._database_name(store, database, persist=True)
        if client.collection_exists(collection_name=name):
            self._assert_collection_owner(client, name, database)
        else:
            try:
                client.create_collection(
                    collection_name=name,
                    **self._create_collection_kwargs(store, database),
                )
            except Exception as error:  # noqa: BLE001
                raise UserError(
                    _("Could not create Qdrant collection '%(name)s': %(error)s", name=name, error=error)
                ) from error
        self._ensure_payload_indexes(client, name, database)
        contract = dict(database.query_contract or {})
        contract.update(
            {
                "version": 1,
                "provider": "qdrant",
                "collection": name,
                "dense_vector": (
                    self._dense_vector_name(database)
                    if database.dense_embedding_model_id
                    else None
                ),
                "sparse_vector": (
                    self._sparse_vector_name(database)
                    if database.sparse_embedding_model_id
                    else None
                ),
                "text_field": "text",
                "embedding_dimension": database.dimension or None,
            }
        )
        database.write({"query_contract": contract})
        return True

    def drop_database(self, store, database, **kwargs):
        self._ensure_dedicated(database)
        client = self._client(store)
        name = self._database_name(store, database)
        if not client.collection_exists(collection_name=name):
            return True
        self._assert_collection_owner(client, name, database)
        result = client.delete_collection(collection_name=name, timeout=DELETE_TIMEOUT)
        if result is False:
            raise UserError(_("Qdrant did not confirm deletion of '%s'.", name))
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
        self._ensure_dedicated(database)
        client = self._client(store)
        name = self._database_name(store, database)
        self._assert_collection_owner(client, name, database)
        points = self._build_points(database, vectors, sparse_vectors, metadata, ids)
        response = client.upsert(
            collection_name=name,
            points=points,
            wait=True,
        )
        if response.status != qdrant_models.UpdateStatus.COMPLETED:
            raise UserError(
                _("Qdrant did not complete the upsert for '%s'.", database.name)
            )
        return list(ids or [])

    def _build_points(self, database, vectors, sparse_vectors, metadata, ids):
        ids = list(ids or [])
        dense = list(vectors) if vectors is not None else None
        sparse = list(sparse_vectors) if sparse_vectors is not None else None
        count = len(ids)
        if not count:
            raise UserError(_("Qdrant upserts require provider record IDs."))
        if dense is not None and len(dense) != count:
            raise UserError(_("Dense vector and provider ID counts must match."))
        if sparse is not None and len(sparse) != count:
            raise UserError(_("Sparse vector and provider ID counts must match."))
        payloads = list(metadata or [{} for _item in ids])
        if len(payloads) != count:
            raise UserError(_("Payload and provider ID counts must match."))

        points = []
        for index, provider_id in enumerate(ids):
            named_vectors = {}
            if dense is not None:
                named_vectors[self._dense_vector_name(database)] = dense[index]
            if sparse is not None:
                value = sparse[index]
                if not isinstance(value, dict) or not {"indices", "values"}.issubset(value):
                    raise UserError(
                        _("Sparse vectors must contain 'indices' and 'values'.")
                    )
                named_vectors[self._sparse_vector_name(database)] = (
                    qdrant_models.SparseVector(
                        indices=value["indices"], values=value["values"]
                    )
                )
            points.append(
                qdrant_models.PointStruct(
                    id=self._point_id(provider_id),
                    vector=named_vectors,
                    payload=self._sanitize_payload(payloads[index]),
                )
            )
        return points

    @staticmethod
    def _point_id(value):
        if isinstance(value, int):
            if value < 0:
                raise UserError(_("Qdrant numeric point IDs cannot be negative."))
            return value
        text = str(value)
        try:
            return str(uuid.UUID(text))
        except (ValueError, TypeError, AttributeError) as error:
            raise UserError(
                _("Qdrant point IDs must be non-negative integers or UUIDs: %s", value)
            ) from error

    @classmethod
    def _sanitize_payload(cls, payload):
        if not isinstance(payload, dict):
            return {}
        return {str(key): cls._sanitize_value(value) for key, value in payload.items()}

    @classmethod
    def _sanitize_value(cls, value):
        if value is None or isinstance(value, (str, int, float, bool)):
            return value
        if isinstance(value, dict):
            return {str(key): cls._sanitize_value(item) for key, item in value.items()}
        if isinstance(value, (list, tuple)):
            return [cls._sanitize_value(item) for item in value]
        return str(value)

    def delete_database_vectors(self, store, database, ids, **kwargs):
        self._ensure_dedicated(database)
        point_ids = [self._point_id(value) for value in (ids or [])]
        if not point_ids:
            return True
        client = self._client(store)
        name = self._database_name(store, database)
        self._assert_collection_owner(client, name, database)
        response = client.delete(
            collection_name=name,
            points_selector=qdrant_models.PointIdsList(points=point_ids),
            wait=True,
        )
        if response.status != qdrant_models.UpdateStatus.COMPLETED:
            raise UserError(
                _("Qdrant did not complete record deletion for '%s'.", database.name)
            )
        return True

    def search_database_vectors(
        self, store, database, query_vector=None, limit=10, filter=None, **kwargs
    ):
        self._ensure_dedicated(database)
        query_filter = self._convert_filter(filter)
        query_mode = kwargs.get("query_mode") or "dense"
        sparse_vector = kwargs.get("sparse_query_vector")
        client = self._client(store)
        name = self._database_name(store, database)
        self._assert_collection_owner(client, name, database)
        common = {
            "collection_name": name,
            "limit": limit or 10,
            "with_payload": True,
            "with_vectors": False,
            "score_threshold": kwargs.get("min_similarity")
            or kwargs.get("score_threshold"),
        }
        common = {key: value for key, value in common.items() if value is not None}

        if query_mode == "dense":
            if query_vector is None:
                raise UserError(_("Dense Qdrant search requires a query vector."))
            result = client.query_points(
                query=query_vector,
                using=self._dense_vector_name(database),
                query_filter=query_filter,
                **common,
            )
        elif query_mode == "sparse":
            result = client.query_points(
                query=self._sparse_query(sparse_vector),
                using=self._sparse_vector_name(database),
                query_filter=query_filter,
                **common,
            )
        elif query_mode == "hybrid":
            result = self._hybrid_query(
                client,
                database,
                query_vector,
                sparse_vector,
                query_filter,
                common,
                kwargs,
            )
        else:
            raise UserError(
                _(
                    "Qdrant query mode '%s' is not configured. Use dense, sparse, "
                    "or provider-side hybrid search.",
                    query_mode,
                )
            )

        return [
            {
                "id": str(hit.id),
                "score": hit.score,
                "payload": hit.payload or {},
                "metadata": hit.payload or {},
            }
            for hit in result.points
        ]

    @staticmethod
    def _sparse_query(value):
        if not isinstance(value, dict) or not {"indices", "values"}.issubset(value):
            raise UserError(_("Sparse Qdrant search requires indices and values."))
        return qdrant_models.SparseVector(
            indices=value["indices"], values=value["values"]
        )

    def _hybrid_query(
        self,
        client,
        database,
        dense_vector,
        sparse_vector,
        query_filter,
        common,
        options,
    ):
        channels = options.get("hybrid_channels") or {}
        prefetch = []
        prefetch_limit = max((common.get("limit") or 10) * 3, 30)
        if channels.get("dense"):
            if dense_vector is None:
                raise UserError(_("Hybrid dense search requires a dense vector."))
            prefetch.append(
                qdrant_models.Prefetch(
                    query=dense_vector,
                    using=self._dense_vector_name(database),
                    filter=query_filter,
                    limit=prefetch_limit,
                )
            )
        if channels.get("sparse"):
            prefetch.append(
                qdrant_models.Prefetch(
                    query=self._sparse_query(sparse_vector),
                    using=self._sparse_vector_name(database),
                    filter=query_filter,
                    limit=prefetch_limit,
                )
            )
        if len(prefetch) < 2:
            raise UserError(_("Qdrant hybrid search requires two vector channels."))
        fusion_method = options.get("fusion_method") or "rrf"
        if fusion_method != "rrf":
            raise UserError(
                _("Qdrant currently supports RRF for this hybrid query contract.")
            )
        return client.query_points(
            prefetch=prefetch,
            query=qdrant_models.FusionQuery(fusion=qdrant_models.Fusion.RRF),
            query_filter=query_filter,
            **common,
        )

    # ------------------------------------------------------------------
    # Filters and indexes
    # ------------------------------------------------------------------
    def _convert_filter(self, value):
        if not value:
            return None
        if isinstance(value, list):
            if not all(isinstance(item, (list, tuple)) and len(item) == 3 for item in value):
                raise UserError(_("Complex Odoo-domain filters are not supported by Qdrant."))
            value = {
                "$and": [
                    {field: self._domain_operator(operator, operand)}
                    for field, operator, operand in value
                ]
            }
        if not isinstance(value, dict):
            raise UserError(_("Qdrant filters must be mappings or flat Odoo domains."))

        must, should, must_not = [], [], []
        for key, operand in value.items():
            if key in ("$and", "$or"):
                if not isinstance(operand, list):
                    raise UserError(_("Filter operator '%s' requires a list.", key))
                children = [self._convert_filter(item) for item in operand]
                children = [item for item in children if item]
                target = must if key == "$and" else should
                target.extend(children)
                continue
            self._add_field_conditions(str(key), operand, must, must_not)
        if not must and not should and not must_not:
            return None
        return qdrant_models.Filter(
            must=must or None, should=should or None, must_not=must_not or None
        )

    @staticmethod
    def _domain_operator(operator, operand):
        mapping = {
            "=": "$eq",
            "!=": "$ne",
            ">": "$gt",
            ">=": "$gte",
            "<": "$lt",
            "<=": "$lte",
            "in": "$in",
            "not in": "$nin",
        }
        if operator not in mapping:
            raise UserError(_("Unsupported Qdrant domain operator '%s'.", operator))
        return {mapping[operator]: operand}

    @staticmethod
    def _add_field_conditions(key, operand, must, must_not):
        if not isinstance(operand, dict):
            operand = {"$eq": operand}
        range_names = {"$gt": "gt", "$gte": "gte", "$lt": "lt", "$lte": "lte"}
        for operator, value in operand.items():
            if operator in ("$eq", "$ne"):
                condition = qdrant_models.FieldCondition(
                    key=key, match=qdrant_models.MatchValue(value=value)
                )
                (must if operator == "$eq" else must_not).append(condition)
            elif operator in range_names:
                must.append(
                    qdrant_models.FieldCondition(
                        key=key,
                        range=qdrant_models.Range(**{range_names[operator]: value}),
                    )
                )
            elif operator in ("$in", "$nin") and isinstance(value, list):
                condition = qdrant_models.FieldCondition(
                    key=key, match=qdrant_models.MatchAny(any=value)
                )
                (must if operator == "$in" else must_not).append(condition)
            else:
                raise UserError(
                    _("Unsupported Qdrant filter operator '%(operator)s' for '%(key)s'.", operator=operator, key=key)
                )

    def create_database_index(self, store, database, index_type=None, **kwargs):
        self._ensure_dedicated(database)
        field_name = kwargs.get("field_name")
        field_schema = kwargs.get("field_schema") or index_type
        if not field_name or not field_schema:
            return True
        client = self._client(store)
        name = self._database_name(store, database)
        self._assert_collection_owner(client, name, database)
        return self._create_payload_index(
            client,
            name,
            field_name,
            field_schema,
            kwargs.get("field_options"),
        )

    def _payload_schema(self, schema, options=None):
        schema_name = str(schema).lower()
        enum_name = _PAYLOAD_SCHEMA_NAMES.get(schema_name)
        enum = getattr(qdrant_models.PayloadSchemaType, enum_name, None) if enum_name else None
        if not enum:
            raise UserError(_("Unsupported Qdrant payload schema '%s'.", schema))
        if not options:
            return enum
        model_names = {
            "keyword": "KeywordIndexParams",
            "integer": "IntegerIndexParams",
            "float": "FloatIndexParams",
            "geo": "GeoIndexParams",
            "text": "TextIndexParams",
            "bool": "BoolIndexParams",
            "datetime": "DatetimeIndexParams",
            "uuid": "UuidIndexParams",
        }
        model = getattr(qdrant_models, model_names[schema_name])
        return model(type=enum, **options)

    def _create_payload_index(self, client, name, field_name, schema, options=None):
        try:
            response = client.create_payload_index(
                collection_name=name,
                field_name=field_name,
                field_schema=self._payload_schema(schema, options),
                wait=True,
            )
        except UnexpectedResponse as error:
            body = error.content.decode() if isinstance(error.content, bytes) else str(error.content)
            if "already exists" in body.lower():
                return True
            raise
        if response.status != qdrant_models.UpdateStatus.COMPLETED:
            raise UserError(_("Qdrant did not create index '%(field)s' on '%(name)s'.", field=field_name, name=name))
        return True

    def _ensure_payload_indexes(self, client, name, database):
        defaults = [
            {"field_name": "store_database_id", "field_schema": "integer"},
            {"field_name": "document_id", "field_schema": "integer"},
            {"field_name": "chunk_id", "field_schema": "integer"},
            {"field_name": "logical_id", "field_schema": "uuid"},
        ]
        configured = self._configuration(database).get("payload_indexes") or []
        by_name = {item["field_name"]: item for item in defaults}
        by_name.update(
            {item["field_name"]: item for item in configured if item.get("field_name")}
        )
        for item in by_name.values():
            self._create_payload_index(
                client,
                name,
                item["field_name"],
                item.get("field_schema", "keyword"),
                item.get("field_options"),
            )

    def sync_database_contract(self, store, database, **kwargs):
        """Publish the current non-secret direct-client query contract."""
        self._ensure_dedicated(database)
        client = self._client(store)
        name = self._database_name(store, database)
        if not client.collection_exists(collection_name=name):
            return False
        self._assert_collection_owner(client, name, database)
        contract = dict(database.query_contract or {})
        contract.update(
            {
                "version": 1,
                "provider": "qdrant",
                "collection": name,
                "dense_vector": (
                    self._dense_vector_name(database)
                    if database.dense_embedding_model_id
                    else None
                ),
                "sparse_vector": (
                    self._sparse_vector_name(database)
                    if database.sparse_embedding_model_id
                    else None
                ),
                "text_field": "text",
                "embedding_dimension": database.dimension or None,
            }
        )
        database.write({"query_contract": contract})
        client.update_collection(
            collection_name=name,
            metadata=self._collection_metadata(store, database),
        )
        return True

    # ------------------------------------------------------------------
    # Optional access-control capability used by llm.store principals
    # ------------------------------------------------------------------
    def access_capabilities(self, store):
        return {
            "credential_type": "qdrant_jwt",
            "grant_scope": "database",
            "supports_immediate_revocation": True,
            "requires_dedicated_database": True,
        }

    def _auth_collection_name(self, store):
        return store._qdrant_registry_name()

    def _ensure_auth_registry(self, store):
        client = self._client(store)
        name = self._auth_collection_name(store)
        if client.collection_exists(collection_name=name):
            self._assert_registry_owner(client, name, store)
        else:
            client.create_collection(
                collection_name=name,
                vectors_config={},
                metadata={
                    "managed_by": "odoo",
                    "resource_type": "qdrant.credential.registry",
                    "store_uuid": store.env.cr.dbname,
                    "store_instance_uuid": store.qdrant_instance_uuid,
                },
            )
        self._create_payload_index(client, name, "credential_key", "keyword")
        return client, name

    @staticmethod
    def _b64url(value):
        return base64.urlsafe_b64encode(value).rstrip(b"=").decode("ascii")

    def _encode_jwt(self, secret, claims):
        header = {"alg": "HS256", "typ": "JWT"}
        encoded_header = self._b64url(
            json.dumps(header, separators=(",", ":")).encode("utf-8")
        )
        encoded_claims = self._b64url(
            json.dumps(claims, separators=(",", ":")).encode("utf-8")
        )
        signing_input = f"{encoded_header}.{encoded_claims}".encode("ascii")
        signature = hmac.new(
            secret.encode("utf-8"), signing_input, hashlib.sha256
        ).digest()
        return f"{encoded_header}.{encoded_claims}.{self._b64url(signature)}"

    def issue_principal_credential(
        self, store, principal, grants, expires_in=None, **kwargs
    ):
        if not principal.active or principal.state != "active":
            raise ValidationError(
                _("Only active Qdrant principals can receive credentials.")
            )
        if principal.store_id != store:
            raise ValidationError(
                _("The Qdrant principal belongs to a different store instance.")
            )
        if not store.qdrant_jwt_rbac:
            raise UserError(
                _("Enable JWT RBAC on this Qdrant store before issuing credentials.")
            )
        if not store.api_key:
            raise UserError(_("The Qdrant administrator secret is required to sign JWTs."))
        now = Datetime.now()
        grants = grants.filtered(
            lambda grant: grant.active
            and (not grant.valid_from or grant.valid_from <= now)
            and (not grant.valid_until or grant.valid_until > now)
        )
        if not grants:
            raise ValidationError(_("The principal has no currently valid database grants."))
        if any(grant.database_id.store_id != store for grant in grants):
            raise ValidationError(_("Every grant must belong to the principal's store."))
        if any(grant.database_id.isolation_mode != "database" for grant in grants):
            raise ValidationError(
                _("Direct Qdrant credentials require dedicated database isolation.")
            )
        if any(grant.database_id.state != "ready" for grant in grants):
            raise ValidationError(_("Every granted database must be ready."))

        ttl = int(expires_in or store.qdrant_default_token_ttl or 86400)
        if ttl <= 0:
            raise ValidationError(_("Credential lifetime must be positive."))
        expires_at = now + timedelta(seconds=ttl)
        grant_expirations = [
            grant.valid_until for grant in grants if grant.valid_until
        ]
        if grant_expirations:
            expires_at = min(expires_at, min(grant_expirations))
        credential_id = str(uuid.uuid4())
        credential_key = f"{principal.subject}:{principal.token_version}:{credential_id}"
        client = self._client(store)
        access = []
        scope = []
        for grant in grants:
            collection = self._database_name(store, grant.database_id)
            if not client.collection_exists(collection_name=collection):
                raise ValidationError(
                    _("Granted Qdrant collection '%s' does not exist.", collection)
                )
            self._assert_collection_owner(client, collection, grant.database_id)
            permission = "rw" if grant.permission == "read_write" else "r"
            access.append({"collection": collection, "access": permission})
            scope.append(
                {
                    "database_id": grant.database_id.id,
                    "database_uuid": grant.database_id.uuid,
                    "collection": collection,
                    "access": permission,
                    "query_contract": dict(grant.database_id.query_contract or {}),
                }
            )

        client, registry = self._ensure_auth_registry(store)
        response = client.upsert(
            collection_name=registry,
            points=[
                qdrant_models.PointStruct(
                    id=credential_id,
                    vector={},
                    payload={
                        "credential_key": credential_key,
                        "subject": principal.subject,
                        "token_version": principal.token_version,
                        "expires_at": Datetime.to_string(expires_at),
                    },
                )
            ],
            wait=True,
        )
        if response.status != qdrant_models.UpdateStatus.COMPLETED:
            raise UserError(_("Qdrant did not activate the credential registry entry."))

        claims = {
            "sub": principal.subject,
            "jti": credential_id,
            "iat": int(now.replace(tzinfo=timezone.utc).timestamp()),
            "exp": int(expires_at.replace(tzinfo=timezone.utc).timestamp()),
            "access": access,
            "value_exists": {
                "collection": registry,
                "matches": [{"key": "credential_key", "value": credential_key}],
            },
        }
        token = self._encode_jwt(store.api_key, claims)
        return {
            "secret": token,
            "credential_type": "qdrant_jwt",
            "provider_credential_id": credential_id,
            "credential_key": credential_key,
            "issued_at": now,
            "expires_at": expires_at,
            "access_snapshot": scope,
            "provider_metadata": {
                "registry_collection": registry,
                "store_instance_uuid": store.qdrant_instance_uuid,
            },
        }

    def revoke_principal_credential(self, store, credential, **kwargs):
        provider_id = credential.provider_credential_id
        if not provider_id:
            return True
        client = self._client(store)
        provider_metadata = credential.provider_metadata or {}
        owner_uuid = provider_metadata.get("store_instance_uuid")
        if owner_uuid and owner_uuid != store.qdrant_instance_uuid:
            raise ValidationError(
                _("The credential was issued by a different Qdrant store instance.")
            )
        registry = provider_metadata.get(
            "registry_collection"
        ) or self._auth_collection_name(store)
        if not client.collection_exists(collection_name=registry):
            return True
        self._assert_registry_owner(client, registry, store)
        response = client.delete(
            collection_name=registry,
            points_selector=qdrant_models.PointIdsList(
                points=[self._point_id(provider_id)]
            ),
            wait=True,
        )
        if response.status != qdrant_models.UpdateStatus.COMPLETED:
            raise UserError(_("Qdrant did not revoke the credential registry entry."))
        return True

    def validate_config(self, store):
        collections = self._client(store).get_collections().collections
        return {"collections": len(collections), "service": "qdrant"}
