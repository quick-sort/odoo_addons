# Copyright 2026 Rui
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

"""Qdrant vector store: one collection per index in an external Qdrant
instance. Vectors use cosine distance; the payload is stored as metadata.
"""

import logging

from odoo import _
from odoo.exceptions import UserError

from odoo.addons.component.core import Component

_logger = logging.getLogger(__name__)


class QdrantStore(Component):
    _name = "qdrant.store"
    _inherit = "knowledge.vector.store.component"
    _usage = "qdrant"

    def _client(self):
        try:
            from qdrant_client import QdrantClient
        except ImportError as err:
            raise UserError(
                _(
                    "The 'qdrant_client' python package is required for the "
                    "Qdrant store. Install it with: pip install qdrant-client"
                )
            ) from err
        return QdrantClient(
            url=self.collection.api_url,
            api_key=self.collection.api_key or None,
            timeout=30,
        )

    def _models(self):
        from qdrant_client.http import models as qm  # noqa: PLC0415

        return qm

    def ensure_index(self, index_name, vector_size):
        qm = self._models()
        client = self._client()
        if client.collection_exists(index_name):
            return
        client.create_collection(
            collection_name=index_name,
            vectors_config=qm.VectorParams(
                size=int(vector_size),
                distance=qm.Distance.COSINE,
            ),
        )

    def upsert(self, index_name, points):
        qm = self._models()
        client = self._client()
        points_obj = [
            qm.PointStruct(id=point_id, vector=vector, payload=payload)
            for point_id, vector, payload in points
        ]
        if points_obj:
            client.upsert(collection_name=index_name, points=points_obj)

    def search(self, index_name, vector, limit=10, filters=None):
        qm = self._models()
        client = self._client()
        query_filter = None
        if filters:
            query_filter = qm.Filter(
                must=[
                    qm.FieldCondition(key=key, match=qm.MatchValue(value=value))
                    for key, value in filters.items()
                ]
            )
        response = client.query_points(
            collection_name=index_name,
            query=vector,
            limit=int(limit),
            query_filter=query_filter,
            with_payload=True,
        )
        results = []
        for point in response.points:
            results.append(
                {
                    "id": point.id,
                    "score": point.score,
                    "payload": point.payload or {},
                }
            )
        return results

    def drop_index(self, index_name):
        client = self._client()
        if client.collection_exists(index_name):
            client.delete_collection(collection_name=index_name)

    def validate_config(self):
        self._client().get_collections()
