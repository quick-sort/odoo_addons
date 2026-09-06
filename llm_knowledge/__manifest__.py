{
    "name": "LLM Knowledge",
    "summary": "Dependency-light knowledge collections and resources for RAG",
    "description": """
        Manages knowledge collections and resources (Odoo records, files, or URLs)
        without forcing document extraction libraries into the core installation.
        File, URL, PDF, HTML, and HTTP implementations are provided by optional
        llm_knowledge extractor, parser, and retriever addons.
    """,
    "category": "Technical",
    "version": "19.0.5.0.0",
    "depends": [
        "llm",
        "component",
        "storage_backend",
        "queue_job",
    ],
    "author": "quick-sort@outlook.com",
    "website": "quick-sort@outlook.com",
    "data": [
        "security/ir.model.access.csv",
        "data/server_actions.xml",
        "data/ir_cron_data.xml",
        "views/llm_resource_views.xml",
        "views/llm_resource_extractor_views.xml",
        "views/llm_knowledge_collection_views.xml",
        "wizards/create_rag_resource_wizard_views.xml",
        "wizards/upload_resource_wizard_views.xml",
        "views/llm_resource_menu.xml",
        "views/menu.xml",
    ],
    "demo": [
        "data/llm_knowledge_demo.xml",
    ],
    "images": ["static/description/banner.jpeg"],
    "license": "LGPL-3",
    "installable": True,
    "application": False,
    "auto_install": False,
}
