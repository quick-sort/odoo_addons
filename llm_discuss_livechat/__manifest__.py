{
    "name": "LLM Discuss Live Chat",
    "summary": """
        Let an LLM Assistant act as a Live Chat operator
    """,
    "description": """
LLM Discuss Live Chat
======================
Companion module for ``llm_discuss``: lets an agent's Discuss bot user be
registered as an operator on one or more ``im_livechat.channel`` records, and
adds the Live-Chat-specific auto-reply trigger (every visitor message in a
session where the agent is the operator).

See ``DESIGN.md`` in this module for details, including how this interacts
with human operators and with Odoo's native ``chatbot.script`` framework.
    """,
    "category": "Productivity, Discuss",
    "version": "19.0.3.0.0",
    "depends": [
        "llm_discuss",
        "im_livechat",
    ],
    "author": "quick-sort@outlook.com",
    "website": "quick-sort@outlook.com",
    "data": [
        "views/llm_agent_views.xml",
    ],
    "license": "LGPL-3",
    "installable": True,
    "application": False,
    "auto_install": False,
}
