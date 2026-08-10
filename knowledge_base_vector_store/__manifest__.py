# Copyright 2026 Rui
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

{
    "name": "Knowledge Base Vector Store",
    "summary": "Chunking and vectorization of knowledge base sources",
    "version": "19.0.1.0.0",
    "category": "Knowledge",
    "author": "Rui",
    "website": "https://github.com/",
    "license": "LGPL-3",
    "depends": [
        "base",
        "knowledge_base",
        "llm",
        "component",
        "queue_job",
        "storage_backend",
        "server_environment",
    ],
    "external_dependencies": {},
    "data": [
        "security/ir.model.access.csv",
        "views/knowledge_splitter_views.xml",
        "views/knowledge_vector_store_views.xml",
        "views/knowledge_vector_views.xml",
        "views/knowledge_chunkset_views.xml",
        "views/knowledge_base_views.xml",
        "views/knowledge_menus.xml",
    ],
    "installable": True,
    "application": True,
}
