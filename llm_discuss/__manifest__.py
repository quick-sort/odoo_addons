{
    "name": "LLM Discuss",
    "summary": """
        Turn any LLM Assistant into an internal bot that answers in Discuss
    """,
    "category": "Productivity, Discuss",
    "version": "19.0.3.0.0",
    "depends": [
        "base",
        "mail",
        "mail_bot",
        "llm",
    ],
    "author": "quick-sort@outlook.com",
    "website": "quick-sort@outlook.com",
    "data": [
        "security/ir.model.access.csv",
        "data/ir_cron_data.xml",
        "views/llm_agent_views.xml",
    ],
    "assets": {
        "web.assets_backend": [
            "llm_discuss/static/src/**/*.js",
            "llm_discuss/static/src/**/*.xml",
        ],
    },
    "license": "LGPL-3",
    "installable": True,
    "application": False,
    "auto_install": False,
}
