{
    "name": "PgVector ORM Field",
    "summary": "Store vector embeddings in Odoo models with the pgvector extension",
    "description": """
PgVector ORM Field
==================
Adds a ``PgVector`` field type so any Odoo model can store vector embeddings in
Odoo's own PostgreSQL database, backed by the pgvector extension.

This addon provides the ORM capability only: the field type and the
``CREATE EXTENSION vector`` bootstrap. It declares no model and no view, and
knows nothing about LLMs.

Managing *external* vector stores (a separate pgvector instance, Qdrant, ...) is
a different concern, handled by the ``llm_store`` addons. Those do not require
Odoo's own database to have the pgvector extension.

Usage:

    from odoo.addons.base_pgvector.fields import PgVector

    class MyModel(models.Model):
        _name = "my.model"

        embedding = PgVector(string="Embedding", dimension=1536)

The ``dimension`` argument is optional; when given, the column is created as
``vector(N)``.
    """,
    "author": "quick-sort@outlook.com",
    "website": "quick-sort@outlook.com",
    "category": "Technical",
    "version": "19.0.1.0.0",
    "depends": ["base"],
    "external_dependencies": {
        "python": ["pgvector", "numpy"],
    },
    "pre_init_hook": "pre_init_hook",
    "license": "LGPL-3",
    "installable": True,
    "application": False,
    "auto_install": False,
}
