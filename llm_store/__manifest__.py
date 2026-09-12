{
    "name": "LLM Vector Store Base",
    "summary": "Store instances and isolated knowledge databases for RAG",
    "description": """
        Separates vector-store service instances from the physical databases
        built for knowledge collections. A store instance owns administrator
        connectivity and can provision many isolated databases. Each database
        stores exactly one knowledge collection using one independently
        benchmarkable chunking, embedding, and index method.
    """,
    "author": "quick-sort@outlook.com",
    "website": "quick-sort@outlook.com",
    "category": "Technical",
    "version": "19.0.2.0.0",
    "depends": ["llm", "llm_knowledge", "component"],
    "data": [
        "security/ir.model.access.csv",
        "views/llm_store_views.xml",
        "views/llm_store_database_views.xml",
        "views/llm_store_menu_views.xml",
        "views/llm_knowledge_splitter_views.xml",
        "views/llm_knowledge_chunkset_views.xml",
        "views/llm_knowledge_vector_views.xml",
        "views/llm_store_chunk_views.xml",
        "views/llm_knowledge_collection_views.xml",
        "views/llm_document_views.xml",
        "views/menu.xml",
    ],
    "demo": ["data/llm_knowledge_splitter_demo.xml"],
    "images": ["static/description/banner.jpeg"],
    "license": "LGPL-3",
    "installable": True,
}
