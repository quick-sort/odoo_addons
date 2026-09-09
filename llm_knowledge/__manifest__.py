{
    "name": "LLM Knowledge",
    "summary": "Single-collection binary-to-Markdown knowledge documents",
    "description": """
        Manages file and URL knowledge documents. Retrieval produces a binary
        envelope, extraction produces Markdown, and collection cache backends
        retain downloaded URL binaries and processed artifacts.
    """,
    "category": "Technical",
    "version": "19.0.7.0.0",
    "depends": ["llm", "component", "storage_backend", "queue_job"],
    "external_dependencies": {"python": ["requests"]},
    "author": "quick-sort@outlook.com",
    "website": "quick-sort@outlook.com",
    "data": [
        "security/ir.model.access.csv",
        "data/server_actions.xml",
        "data/ir_cron_data.xml",
        "views/llm_document_views.xml",
        "views/llm_document_extractor_views.xml",
        "views/llm_document_extractor_mapping_views.xml",
        "views/llm_knowledge_collection_views.xml",
        "wizards/upload_document_wizard_views.xml",
        "views/llm_document_menu.xml",
        "views/menu.xml",
    ],
    "demo": ["data/llm_knowledge_demo.xml"],
    "images": ["static/description/banner.jpeg"],
    "license": "LGPL-3",
    "installable": True,
    "application": False,
    "auto_install": False,
}
