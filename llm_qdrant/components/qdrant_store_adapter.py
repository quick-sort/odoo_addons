"""Qdrant as an ``llm.store`` service.

Implements the ``llm.store.adapter`` contract for ``service == "qdrant"``.

Every method takes the ``llm.store`` record as its first argument instead of
reading ``self.collection``, which keeps the pure payload/filter/id logic
testable without a database or a running Qdrant server.

Consistency: writes do not participate in the Odoo transaction, so an Odoo
rollback after a successful upsert can leave orphan points -- the same property
the external pgvector adapter has.
"""

import logging

from qdrant_client import QdrantClient
from qdrant_client import models as qdrant_models
from qdrant_client.http.exceptions import UnexpectedResponse

from odoo import _
from odoo.exceptions import UserError

from odoo.addons.component.core import Component

_logger = logging.getLogger(__name__)

DEFAULT_HOST = "localhost"
DEFAULT_PORT = 6333
DELETE_TIMEOUT = 30

PAYLOAD_SCHEMA_TYPES = {
    "keyword": qdrant_models.PayloadSchemaType.KEYWORD,
    "integer": qdrant_models.PayloadSchemaType.INTEGER,
    "float": qdrant_models.PayloadSchemaType.FLOAT,
    "geo": qdrant_models.PayloadSchemaType.GEO,
    "text": qdrant_models.PayloadSchemaType.TEXT,
}


class QdrantStoreAdapter(Component):
    _name = "qdrant.store.adapter"
    _inherit = "llm.store.adapter"
    _usage = "qdrant"

    # ------------------------------------------------------------------
    # Client
    # ------------------------------------------------------------------

    def _client(self, store):
        """Build a Qdrant client from the store configuration."""
        kwargs = {}
        if store.connection_uri:
            kwargs["url"] = store.connection_uri
        else:
            kwargs["host"] = DEFAULT_HOST
            kwargs["port"] = DEFAULT_PORT

        if store.api_key:
            kwargs["api_key"] = store.api_key

        try:
            return QdrantClient(**kwargs)
        except Exception as err:
            _logger.error(
                "Failed to connect to Qdrant server at %s: %s",
                kwargs.get("url") or kwargs.get("host"),
                err,
            )
            raise UserError(
                _(
                    "Could not connect to the Qdrant vector database server.\n\n"
                    "Please check:\n"
                    "• The server is running at the configured address\n"
                    "• The API key (if required) is correct\n"
                    "• Network/firewall allows the connection\n\n"
                    "Technical details: %(error)s",
                    error=err,
                ),
            ) from err

    # ------------------------------------------------------------------
    # Collections
    # ------------------------------------------------------------------

    def sanitize_collection_name(self, store, name):
        """Qdrant accepts the generic naming rules of ``llm.store``."""
        return store._default_sanitize_collection_name(name)

    def collection_exists(self, store, name, **kwargs):
        return self._client(store).collection_exists(
            collection_name=store.get_santized_collection_name(name),
        )

    def create_collection(
        self,
        store,
        collection_id,
        dimension=None,
        metadata=None,
        **kwargs,
    ):
        """Create a cosine-distance collection, sized from ``dimension``.

        When no dimension is given, it is probed from the knowledge
        collection's embedding model. That lookup is optional: the adapter
        stays usable without ``llm_knowledge`` installed, in which case an
        explicit ``dimension`` is required.
        """
        client = self._client(store)
        name = store.get_santized_collection_name(collection_id)

        if not dimension:
            dimension = self._probe_dimension(store, collection_id)
        if not dimension:
            raise UserError(
                _(
                    "A vector dimension is required to create Qdrant collection "
                    "'%(name)s' and it could not be derived from the collection's "
                    "embedding model.",
                    name=name,
                ),
            )

        if client.collection_exists(collection_name=name):
            # Pre-existing collection: left untouched. A dimension mismatch is
            # not detected here, upserts would fail later.
            return True

        try:
            client.create_collection(
                collection_name=name,
                vectors_config=qdrant_models.VectorParams(
                    size=dimension,
                    distance=qdrant_models.Distance.COSINE,
                ),
            )
            return True
        except UnexpectedResponse as err:
            _logger.exception(
                "Could not create collection %s: %s - %s",
                name,
                err.status_code,
                err.content.decode(),
            )
            return False

    @staticmethod
    def _probe_dimension(store, collection_id):
        """Derive the vector size from the knowledge collection, if available.

        Returns ``None`` when ``llm_knowledge`` is not installed, the record is
        gone, or it has no embedding model -- the caller then requires an
        explicit dimension.
        """
        env = store.env
        if "llm.knowledge.collection" not in env:
            return None

        record = env["llm.knowledge.collection"].browse(collection_id)
        if not record.exists() or not record.embedding_model_id:
            return None

        # One throwaway embedding is the only reliable way to learn the size.
        sample = record.embedding_model_id.embedding("")
        return len(sample[0]) if sample and sample[0] else None

    def delete_collection(self, store, collection_id, **kwargs):
        client = self._client(store)
        name = store.get_santized_collection_name(collection_id)

        if not client.collection_exists(collection_name=name):
            return True

        result = client.delete_collection(
            collection_name=name,
            timeout=DELETE_TIMEOUT,
        )
        if result is not True:
            _logger.warning(
                "Qdrant delete_collection for %s returned %s. "
                "Assuming success since no exception was raised.",
                name,
                result,
            )
        return True

    def list_collections(self, store, **kwargs):
        return [c.name for c in self._client(store).get_collections().collections]

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
        """Upsert points. ``ids`` must line up with ``vectors``."""
        client = self._client(store)
        name = store.get_santized_collection_name(collection_id)

        points = self._build_points(vectors, metadata, ids)

        response = client.upsert(collection_name=name, points=points, wait=True)
        if response.status != qdrant_models.UpdateStatus.COMPLETED:
            _logger.warning(
                "Qdrant upsert status for collection %s: %s",
                name,
                response.status,
            )
        return ids

    def _build_points(self, vectors, metadata, ids):
        """Turn parallel lists into ``PointStruct`` objects.

        Kept separate from the client call so the id and payload rules can be
        tested without a server.
        """
        vectors = list(vectors or [])
        if not ids or len(ids) != len(vectors):
            raise UserError(
                _("Must provide unique IDs matching the number of vectors."),
            )

        points = []
        for index, vec_id in enumerate(ids):
            point_id = self._point_id(vec_id)
            payload = metadata[index] if metadata and index < len(metadata) else {}
            points.append(
                qdrant_models.PointStruct(
                    id=point_id,
                    vector=vectors[index],
                    payload=self._sanitize_payload(payload),
                ),
            )
        return points

    @staticmethod
    def _point_id(vec_id):
        """Coerce an id to a non-negative integer, as Qdrant requires."""
        try:
            point_id = int(vec_id)
        except (TypeError, ValueError) as err:
            raise UserError(
                _(
                    "Qdrant vector IDs must be non-negative integers or UUIDs. "
                    "Received: %(value)s",
                    value=vec_id,
                ),
            ) from err
        if point_id < 0:
            raise UserError(
                _(
                    "Qdrant vector IDs must be non-negative integers or UUIDs. "
                    "Received: %(value)s",
                    value=vec_id,
                ),
            )
        return point_id

    @staticmethod
    def _sanitize_payload(payload):
        """Reduce a payload to JSON-serializable scalars, lists and None.

        Anything else is stringified rather than dropped, so information is
        preserved even when it cannot be filtered on.
        """
        if not isinstance(payload, dict):
            return {}

        clean = {}
        for key, value in payload.items():
            if value is None or isinstance(value, (str, int, float, bool)):
                clean[key] = value
            elif isinstance(value, list):
                scalar_only = all(
                    item is None or isinstance(item, (str, int, float, bool))
                    for item in value
                )
                clean[key] = value if scalar_only else str(value)
            else:
                clean[key] = str(value)
        return clean

    def delete_vectors(self, store, collection_id, ids, **kwargs):
        if not ids:
            return False

        point_ids = self._usable_point_ids(ids)
        if not point_ids:
            return False

        client = self._client(store)
        name = store.get_santized_collection_name(collection_id)

        response = client.delete(
            collection_name=name,
            points_selector=qdrant_models.PointIdsList(points=point_ids),
            wait=True,
        )
        if response.status != qdrant_models.UpdateStatus.COMPLETED:
            _logger.warning(
                "Qdrant delete status for collection %s: %s",
                name,
                response.status,
            )
            return False
        return True

    @staticmethod
    def _usable_point_ids(ids):
        """Keep only the ids Qdrant can address, warning about the rest.

        Deletion is best-effort on purpose: an unusable id means there is
        nothing to delete, which should not abort the whole call.
        """
        usable = [
            int(vid) for vid in ids if str(vid).isdigit() and int(vid) >= 0
        ]
        if len(usable) != len(ids):
            _logger.warning(
                "Some provided IDs for deletion were invalid "
                "(non-integer or negative), skipping them.",
            )
        return usable

    def search_vectors(
        self,
        store,
        collection_id,
        query_vector,
        limit=10,
        filter=None,  # noqa: A002 - name kept for the llm.store contract
        min_similarity=0.5,
        **kwargs,
    ):
        """Similarity search, returning ``id`` / ``score`` / ``metadata`` dicts."""
        client = self._client(store)
        name = store.get_santized_collection_name(collection_id)

        result = client.query_points(
            collection_name=name,
            query=query_vector,
            query_filter=self._convert_filter(filter) if filter else None,
            limit=limit,
            score_threshold=min_similarity,
            with_payload=True,
            with_vectors=False,
        )

        return [
            {
                "id": hit.id,
                "score": hit.score,
                "metadata": hit.payload or {},
            }
            for hit in result.points
        ]

    def _convert_filter(self, odoo_filter):
        """Translate a Mongo-style filter dict into a Qdrant ``Filter``.

        Supports ``$and`` plus the per-field operators ``$eq``, ``$ne``,
        ``$gt``, ``$gte``, ``$lt``, ``$lte``, ``$in``, ``$nin``, and bare
        scalars as equality. ``$or`` is not supported: Qdrant expresses it with
        ``should``, which does not compose with the ``must``/``must_not``
        accumulation used here.

        Returns ``None`` when nothing usable was produced, which the caller
        treats as "no filter".
        """
        if not odoo_filter or not isinstance(odoo_filter, dict):
            return None

        must, must_not = [], []

        for key, value in odoo_filter.items():
            if key == "$and" and isinstance(value, list):
                for condition in value:
                    sub = self._convert_filter(condition)
                    if not sub:
                        continue
                    must.extend(sub.must or [])
                    must_not.extend(sub.must_not or [])
            elif key == "$or":
                _logger.warning(
                    "'$or' operator in filters is not supported yet for Qdrant.",
                )
            elif isinstance(value, dict):
                self._add_field_conditions(f"payload.{key}", key, value, must, must_not)
            elif isinstance(value, (str, int, float, bool)):
                must.append(
                    qdrant_models.FieldCondition(
                        key=f"payload.{key}",
                        match=qdrant_models.MatchValue(value=value),
                    ),
                )
            else:
                _logger.warning(
                    "Unsupported filter value type for key '%s': %s",
                    key,
                    type(value),
                )

        if not must and not must_not:
            return None

        return qdrant_models.Filter(
            must=must or None,
            must_not=must_not or None,
        )

    @staticmethod
    def _add_field_conditions(field_key, key, operators, must, must_not):
        """Append the conditions for one field's operator dict, in place."""
        ranges = {"$gt": "gt", "$gte": "gte", "$lt": "lt", "$lte": "lte"}

        for operator, operand in operators.items():
            if operator == "$eq":
                must.append(
                    qdrant_models.FieldCondition(
                        key=field_key,
                        match=qdrant_models.MatchValue(value=operand),
                    ),
                )
            elif operator == "$ne":
                must_not.append(
                    qdrant_models.FieldCondition(
                        key=field_key,
                        match=qdrant_models.MatchValue(value=operand),
                    ),
                )
            elif operator in ranges:
                must.append(
                    qdrant_models.FieldCondition(
                        key=field_key,
                        range=qdrant_models.Range(**{ranges[operator]: operand}),
                    ),
                )
            elif operator == "$in" and isinstance(operand, list):
                must.append(
                    qdrant_models.FieldCondition(
                        key=field_key,
                        match=qdrant_models.MatchAny(any=operand),
                    ),
                )
            elif operator == "$nin" and isinstance(operand, list):
                must_not.append(
                    qdrant_models.FieldCondition(
                        key=field_key,
                        match=qdrant_models.MatchAny(any=operand),
                    ),
                )
            else:
                _logger.warning(
                    "Unsupported filter operator '%s' for key '%s'",
                    operator,
                    key,
                )

    # ------------------------------------------------------------------
    # Indexes
    # ------------------------------------------------------------------

    def create_index(self, store, collection_id, index_type=None, **kwargs):
        """Create a payload index on one field.

        Qdrant indexes vectors automatically, so this only covers *payload*
        indexes, which speed up filtered search. Without ``field_name`` and
        ``field_schema`` there is nothing to do and the call succeeds.
        """
        field_name = kwargs.get("field_name")
        field_schema = kwargs.get("field_schema")
        if not field_name or not field_schema:
            return True

        schema_type = PAYLOAD_SCHEMA_TYPES.get(str(field_schema).lower())
        if not schema_type:
            raise UserError(
                _(
                    "Unsupported field_schema '%(schema)s'. Must be one of: %(known)s",
                    schema=field_schema,
                    known=", ".join(sorted(PAYLOAD_SCHEMA_TYPES)),
                ),
            )

        client = self._client(store)
        name = store.get_santized_collection_name(collection_id)

        try:
            response = client.create_payload_index(
                collection_name=name,
                field_name=field_name,
                field_schema=schema_type,
                wait=True,
            )
            if response.status != qdrant_models.UpdateStatus.COMPLETED:
                _logger.warning(
                    "Qdrant create_payload_index status for %s.%s: %s",
                    name,
                    field_name,
                    response.status,
                )
                return False
            return True
        except UnexpectedResponse as err:
            body = err.content.decode()
            _logger.error(
                "Error creating payload index on %s.%s: %s - %s",
                name,
                field_name,
                err.status_code,
                body,
            )
            # An already-existing index is the desired end state, not a failure.
            return "already exists" in body.lower()

    # ------------------------------------------------------------------
    # Connectivity
    # ------------------------------------------------------------------

    def validate_config(self, store):
        """Check the server answers, for the store's Test Connection button."""
        collections = self._client(store).get_collections().collections
        return {"collections": len(collections)}
