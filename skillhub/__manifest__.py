{
    "name": "Skills Hub",
    "version": "19.0.2.0.0",
    "category": "Productivity",
    "summary": "Skill package registry: publish/search/share/download skill zips over MCP",
    "author": "quick-sort@outlook.com",
    "website": "",
    "license": "LGPL-3",
    "depends": [
        "llm_mcp_server",
        "llm",
    ],
    "external_dependencies": {},
    "data": [
        "security/ir.model.access.csv",
        "security/skillhub_security.xml",
        "data/skillhub_guide.xml",
        "views/skillhub_skill_views.xml",
        "views/skillhub_category_views.xml",
        "views/skillhub_menus.xml",
    ],
    "application": True,
    "auto_install": False,
}
