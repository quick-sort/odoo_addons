{
    "name": "LLM Discuss",
    "summary": """
        Turn any LLM Assistant into an internal bot that answers in Discuss
    """,
    "description": """
LLM Discuss
===========
Bridges the ``llm`` module's assistants with Odoo's Discuss app.

Any ``llm.assistant`` can be promoted to an internal Discuss bot:

- A dedicated technical ``res.users`` account can represent the assistant in
  direct chats, channels, and Live Chat.
- One assistant can instead take over the existing OdooBot private chat after
  each user's native onboarding is complete. The visible identity remains
  OdooBot, but hidden threads and tools execute with the sender's permissions.
- Replies are generated asynchronously and posted as one complete native
  message; Odoo's native typing state is used while generation is running.

See ``DESIGN.md`` in this module for the full architecture write-up.

Live Chat support (assigning a dedicated assistant bot as an operator) is
provided by the companion module ``llm_discuss_livechat``.
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
        "views/llm_assistant_views.xml",
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
