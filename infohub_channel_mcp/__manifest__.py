{
    "name": "InfoHub MCP Channel",
    "summary": "Pull news from a third-party MCP tool into the InfoHub pool",
    "description": """
InfoHub — MCP channel
=====================

Adds ``mcp`` to ``infohub.channel.channel_type`` and pulls items from a tool
exposed by an MCP server.

This is the only InfoHub addon that depends on ``llm``. Keeping the dependency
here rather than in the core means a deployment that only wants RSS or email
never installs the LLM stack.

An MCP tool describes nothing about its reply, so results are normalised
defensively: a JSON document is decoded, a list is taken as-is, and a dict is
probed for common envelope keys. A tool that renames its envelope therefore
yields no items instead of raising. Every field the tool returned is preserved
in ``raw_data``, since that is what a channel's ``filter_domain`` matches on.

Credentials are not duplicated: the endpoint URL and API key live on the
``llm.mcp.client`` record, and the channel only references it.
    """,
    "version": "19.0.1.0.0",
    "author": "quick-sort@outlook.com",
    "website": "quick-sort@outlook.com",
    "license": "LGPL-3",
    "category": "Productivity",
    "depends": ["infohub", "llm"],
    "data": [
        "views/infohub_channel_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
