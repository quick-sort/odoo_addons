{
    "name": "LLM Qdrant Integration",
    "version": "19.0.2.0.0",
    "category": "Technical",
    "summary": "Qdrant databases and direct-client access control for LLM Knowledge",
    "description": """
Implements the database-scoped llm.store contract with Qdrant, including
named dense/sparse vectors, canonical chunk payloads, collection ownership,
and collection-scoped JWT credentials for direct RAG clients.
    """,
    "author": "quick-sort@outlook.com",
    "website": "quick-sort@outlook.com",
    "depends": ["llm_knowledge"],
    "external_dependencies": {"python": ["qdrant_client"]},
    "data": [
        "security/ir.model.access.csv",
        "views/llm_store_qdrant_views.xml",
    ],
    "images": ["static/description/banner.jpeg"],
    "installable": True,
    "application": False,
    "auto_install": False,
    "license": "LGPL-3",
}
