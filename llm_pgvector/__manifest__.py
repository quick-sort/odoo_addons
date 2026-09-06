{
    "name": "LLM PgVector (external instance)",
    "summary": "Use a standalone pgvector PostgreSQL instance as an LLM vector store",
    "description": """
LLM PgVector (external instance)
================================
Registers a standalone pgvector server as the ``pgvector`` service of
``llm.store``, alongside Qdrant. Vectors are stored on that external server,
reached over its own connection built from the store's connection URI.

Deliberately independent from Odoo's database:

- Odoo's own database does **not** need the pgvector extension, so no superuser
  step is required to start using this;
- no dependency on ``llm_knowledge``;
- Odoo's cursor is never used -- every statement runs on the external
  connection.

Storing embeddings *inside* Odoo's own database is a different feature, with
different trade-offs (transactional writes, cascade deletes, single-query
filtering). That one is ``llm_knowledge_pgvector``, registered as the
``pgvector_local`` service.

Consistency: as with Qdrant, writes do not participate in the Odoo
transaction, so an Odoo rollback after a successful insert can leave orphan
vectors. Payloads carry the Odoo-side ids so a reconciliation pass can clean
them up.
    """,
    "category": "Technical",
    "version": "19.0.2.0.1",
    "author": "quick-sort@outlook.com",
    "website": "quick-sort@outlook.com",
    "depends": ["llm", "llm_store"],
    "demo": ["data/llm_store_demo.xml"],
    "external_dependencies": {
        "python": ["psycopg2", "pgvector"],
    },
    "images": ["static/description/banner.jpeg"],
    "installable": True,
    "application": False,
    "auto_install": False,
    "license": "LGPL-3",
}
