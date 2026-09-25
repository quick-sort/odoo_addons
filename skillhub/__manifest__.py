{
    "name": "SkillHub",
    "version": "19.0.1.1.0",
    "category": "Productivity",
    "summary": "Skill package registry: publish/search/share/download skill zips over MCP",
    "author": "quick-sort@outlook.com",
    "website": "",
    "license": "LGPL-3",
    "depends": [
        "storage_backend_mcp",
        "llm",
    ],
    "external_dependencies": {},
    "data": [
        "security/ir.model.access.csv",
        "security/skillhub_security.xml",
        "views/skillhub_skill_views.xml",
        "views/skillhub_menus.xml",
    ],
    "application": True,
    "auto_install": False,
}
