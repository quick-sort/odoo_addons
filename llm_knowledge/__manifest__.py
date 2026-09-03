{
    "name": "LLM Knowledge",
    "summary": "RAG vector search: AI knowledge base with semantic document retrieval, embeddings, PDF parsing, and multi-store support (Qdrant, pgvector, Chroma)",
    "description": """
        Complete RAG (Retrieval-Augmented Generation) system for Odoo with document processing,
        vector search, and semantic knowledge base capabilities. Turn your documents into AI-searchable
        knowledge with support for PDFs, web pages, and text files. Compatible with Qdrant, pgvector,
        and Chroma vector stores.
    """,
    "category": "Technical",
    "version": "19.0.2.0.0",
    "depends": [
        "llm",
        "llm_store",
        "component",
        "storage_backend",
        "one_storage",
        "queue_job",
    ],
    "external_dependencies": {
        "python": ["requests", "markdownify", "PyMuPDF", "numpy"],
    },
    "author": "quick-sort@outlook.com",
    "website": "quick-sort@outlook.com",
    "data": [
        # Security must come first
        "security/ir.model.access.csv",
        # Data / Actions
        "data/server_actions.xml",
        # Views for models
        "views/llm_resource_views.xml",  # Consolidated llm.resource views
        "views/llm_resource_extractor_views.xml",
        "views/llm_knowledge_splitter_views.xml",
        "views/llm_knowledge_chunkset_views.xml",
        "views/llm_knowledge_vector_views.xml",
        "views/llm_knowledge_collection_views.xml",
        "views/llm_knowledge_chunk_views.xml",
        # Wizard Views
        "wizards/create_rag_resource_wizard_views.xml",
        "wizards/upload_resource_wizard_views.xml",
        # Menus must come last
        "views/llm_resource_menu.xml",
        "views/menu.xml",
    ],
    "images": [
        "static/description/banner.jpeg",
    ],
    "license": "LGPL-3",
    "installable": True,
    "application": False,
    "auto_install": False,
}
