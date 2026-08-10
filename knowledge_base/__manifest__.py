# Copyright 2026 Rui
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

{
    "name": "Knowledge Base",
    "summary": "Knowledge bases composed of files and URLs, extracted to markdown",
    "version": "19.0.1.0.0",
    "category": "Knowledge",
    "author": "Rui",
    "website": "https://github.com/",
    "license": "LGPL-3",
    "depends": [
        "base",
        "component",
        "queue_job",
        "storage_backend",
        "one_storage",
        "server_environment",
    ],
    "external_dependencies": {},
    "data": [
        "security/knowledge_base_security.xml",
        "data/queue_data.xml",
        "views/knowledge_base_views.xml",
        "views/knowledge_extractor_views.xml",
        "views/knowledge_menus.xml",
        "security/ir.model.access.csv",
    ],
    "installable": True,
    "application": True,
}
