{
    "name": "Storage Backend MCP",
    "version": "19.0.1.0.0",
    "category": "Storage",
    "summary": "MCP/LLM tools for storage backends: temporary upload/download URLs and staged uploads",
    "author": "quick-sort@outlook.com",
    "website": "",
    "license": "LGPL-3",
    "depends": [
        "storage_backend",
        "llm",
    ],
    "external_dependencies": {},
    "data": [
        "security/ir.model.access.csv",
        "data/ir_config_parameter.xml",
        "data/ir_cron_data.xml",
        "views/storage_backend_views.xml",
    ],
    "demo": [],
    "application": False,
    "auto_install": False,
}
