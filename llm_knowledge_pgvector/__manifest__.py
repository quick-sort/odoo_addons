{
    "name": "LLM Knowledge PgVector (in-database)",
    "summary": "Store knowledge chunk embeddings in Odoo's own database with pgvector",
    "description": """
LLM Knowledge PgVector (in-database)
====================================
Stores knowledge chunk embeddings *inside Odoo's own PostgreSQL database*,
using the ``PgVector`` ORM field from ``base_pgvector``.

Because the vectors live in an Odoo table (``llm_knowledge_chunk_embedding``),
this backend gets properties an external store cannot offer:

- embedding writes take part in the Odoo transaction, so a rollback rolls the
  vectors back too;
- ``ondelete="cascade"`` on the chunk means Postgres removes the embeddings
  when a chunk is deleted;
- ``UNIQUE(chunk_id, embedding_model_id)`` is enforced by the database;
- similarity search can filter on ``resource_id`` / collections in the same
  SQL statement, with no second round trip.

The trade-off is that Odoo's own database must have the pgvector extension,
which requires a superuser to run ``CREATE EXTENSION vector`` once.

It registers on ``llm.store`` as the ``pgvector_local`` service. Managing a
*standalone* pgvector instance is a different feature, provided by the
``llm_pgvector`` addon, which has none of the requirements above.
    """,
    "category": "Technical",
    "version": "19.0.1.0.0",
    "author": "quick-sort@outlook.com",
    "website": "quick-sort@outlook.com",
    "depends": ["base_pgvector", "llm", "llm_knowledge", "llm_store"],
    "data": [
        "security/ir.model.access.csv",
        "views/llm_knowledge_chunk_embedding_views.xml",
        "views/llm_store_views.xml",
        "views/menu_views.xml",
    ],
    "images": ["static/description/banner.jpeg"],
    "installable": True,
    "application": False,
    "auto_install": False,
    "license": "LGPL-3",
}
