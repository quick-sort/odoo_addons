{
    "name": "LLM Qdrant Integration",
    "version": "19.0.1.0.0",
    "category": "Technical",
    "summary": "Integrates Qdrant vector store with the Odoo LLM framework.",
    "description": """
Provides an llm.store implementation using the Qdrant vector database.
Requires the qdrant-client Python package.
    """,
    "author": "quick-sort@outlook.com",
    "website": "quick-sort@outlook.com",
    "depends": ["llm", "llm_store"],
    "external_dependencies": {
        "python": ["qdrant-client"],
    },
    "images": ["static/description/banner.jpeg"],
    "installable": True,
    "application": False,
    "auto_install": False,
    "license": "LGPL-3",
}
