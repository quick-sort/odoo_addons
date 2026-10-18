{
    "name": "Odoo User Guides for LLM",
    "version": "19.0.1.0.0",
    "license": "LGPL-3",
    "author": "quick-sort@outlook.com",
    "depends": ["llm", "queue_job"],
    "data": [
        "security/ir.model.access.csv",
        "views/llm_odoo_guide_sync_views.xml",
        "data/llm_tool_guide_data.xml",
        "data/llm_tool_guide_meta.xml",
        "data/llm_odoo_guide_sync_data.xml",
    ],
    "installable": True,
    "application": False,
}
