# Copyright 2026 Rui
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

{
    "name": "Agent",
    "summary": "LLM agent framework with component-based polymorphism",
    "version": "19.0.1.0.0",
    "category": "Technical",
    "author": "Rui",
    "website": "https://github.com/",
    "license": "LGPL-3",
    "depends": [
        "component",
        "component_event",
        "llm",
        "llm_tool",
        "llm_thread",
    ],
    "data": [
        "security/agent_security.xml",
        "security/ir.model.access.csv",
        "views/agent_views.xml",
        "views/agent_menus.xml",
    ],
    "installable": True,
    "application": True,
}
