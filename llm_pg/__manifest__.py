{
    "name": "LLM PostgreSQL Control Plane",
    "summary": "Manage remote PostgreSQL knowledge databases and capabilities",
    "category": "Technical",
    "version": "19.0.1.0.0",
    "author": "quick-sort@outlook.com",
    "depends": ["llm_knowledge", "component"],
    "external_dependencies": {"python": ["psycopg2"]},
    "data": [
        "security/ir.model.access.csv",
        "views/llm_store_views.xml",
        "views/llm_store_database_views.xml",
    ],
    "license": "LGPL-3",
    "installable": True,
    "application": False,
    "auto_install": False,
}
