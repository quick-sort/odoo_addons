{
    "name": "InfoHub Agent",
    "summary": "LLM tagging agent for InfoHub news items",
    "description": """
InfoHub — Agent
===============

Tags ``infohub.item`` records with a fixed taxonomy using an LLM agent.

A scheduled cron picks up items in ``tagging_state = pending`` and enqueues
queue jobs that batch-tag them through the seeded "InfoHub Tagger"
(``llm.agent``, code ``infohub_tagger``). Only item titles are sent to the
model, and the agent carries no tools — the model can only ever pick tag
codes from the taxonomy configured on ``infohub.tag`` records.

Keeping the ``llm`` dependency here rather than in the core follows the same
split as ``infohub_channel_mcp``: a deployment that only wants RSS or email
never installs the LLM stack.
    """,
    "version": "19.0.1.0.0",
    "author": "quick-sort@outlook.com",
    "website": "quick-sort@outlook.com",
    "license": "LGPL-3",
    "category": "Productivity",
    "depends": ["infohub", "llm"],
    "data": [
        "security/ir.model.access.csv",
        "data/llm_agent_tag_data.xml",
        "data/llm_agent_data.xml",
        "data/ir_cron_data.xml",
        "views/infohub_tag_views.xml",
        "views/infohub_item_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
