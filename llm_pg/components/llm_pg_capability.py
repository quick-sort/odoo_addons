"""Composable PostgreSQL database capability contract."""

from odoo.addons.component.core import AbstractComponent


class LLMPgCapabilityAdapter(AbstractComponent):
    _name = "llm.pg.capability.adapter"
    _collection = "llm.store"

    def required_extensions(self, store, database, capability):
        return tuple(capability.capability_id.extension_names or [])

    def probe_runtime(self, store, database, capability, cursor):
        return {"ready": True}

    def provision_schema(
        self, store, database, capability, cursor, schema_name, table_name
    ):
        return True

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
        return None

    def supports_query(self, mode):
        return False

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
        raise NotImplementedError

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
        return []
