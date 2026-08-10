# Copyright 2026 Rui
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

"""Base class for knowledge vector store components.

The component talks to one external vector database instance (configured on
the ``knowledge.vector.store`` record). Index/collection names are passed in
by the caller (``knowledge.vector``) so a single store instance can host many
indexes.

Points are ``(point_id, vector, payload)`` tuples; search returns a list of
``{"id", "score", "payload"}`` dicts.
"""

from odoo.addons.component.core import AbstractComponent


class KnowledgeVectorStoreComponent(AbstractComponent):
    _name = "knowledge.vector.store.component"
    _collection = "knowledge.vector.store"

    def ensure_index(self, index_name, vector_size):
        """Create the index/collection if it does not exist."""
        raise NotImplementedError

    def upsert(self, index_name, points):
        """Insert or update the given points."""
        raise NotImplementedError

    def search(self, index_name, vector, limit=10, filters=None):
        """Return the ``limit`` closest points as ``{"id", "score", "payload"}``."""
        raise NotImplementedError

    def drop_index(self, index_name):
        """Delete the index/collection."""
        raise NotImplementedError

    def validate_config(self):
        """Optional connectivity self-test. Raise on failure."""
