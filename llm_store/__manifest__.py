{
    "name": "LLM Vector Store Base",
    "summary": """
        Integration with various vector database providers for LLM applications""",
    "description": """
        Provides integration with vector stores for:
        - Vector storage and retrieval
        - Similarity search
        - Collection management
        - RAG (Retrieval Augmented Generation) support

    """,
    "author": "quick-sort@outlook.com",
    "website": "quick-sort@outlook.com",
    "category": "Technical",
    "version": "19.0.1.0.0",
    "depends": ["llm"],
    "data": [
        "security/ir.model.access.csv",
        "views/llm_store_views.xml",
        "views/llm_store_menu_views.xml",
    ],
    "images": ["static/description/banner.jpeg"],
    "license": "LGPL-3",
    "installable": True,
}
