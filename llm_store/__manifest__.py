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
    "version": "19.0.2.0.0",
    "depends": ["llm", "llm_knowledge", "component"],
    "data": [
        "security/ir.model.access.csv",
        "views/llm_store_views.xml",
        "views/llm_store_menu_views.xml",
        "views/llm_knowledge_splitter_views.xml",
        "views/llm_knowledge_chunkset_views.xml",
        "views/llm_knowledge_vector_views.xml",
        "views/llm_store_chunk_views.xml",
        "views/llm_knowledge_collection_views.xml",
        "views/llm_resource_views.xml",
        "views/menu.xml",
    ],
    "demo": [
        "data/llm_knowledge_splitter_demo.xml",
    ],
    "images": ["static/description/banner.jpeg"],
    "license": "LGPL-3",
    "installable": True,
}
