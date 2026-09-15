{
    "name": "InfoHub",
    "summary": "Aggregate news from many sources through pluggable channels",
    "description": """
InfoHub — news aggregation
==========================

Collects news items into a single pool. Two orthogonal notions:

* **Source** — whose the news is, e.g. a journal or a news site.
* **Channel** — how it is obtained, e.g. RSS, an inbound newsletter email, or a
  third-party API.

The same source may be reachable through several channels, so an item carries
both: ``source_id`` says who it belongs to, ``channel_id`` says how it arrived.

Channel types are provided by addons that depend on this one:

* ``infohub_channel_rss`` — RSS / Atom feeds
* ``infohub_channel_email`` — inbound newsletter email
* ``infohub_channel_mcp`` — third-party MCP tools / APIs

Channels are ``component`` collections. A channel addon contributes a
``selection_add`` value on ``channel_type``, its own configuration fields via
``_inherit``, and ``infohub.fetch.<type>`` / ``infohub.content.<type>``
components. This core knows nothing about any specific channel and does not
depend on ``llm``.

Outbound HTTP goes through ``url_guard`` (scheme allowlist, private-range /
loopback / link-local blocking, per-hop redirect rechecks).
    """,
    "version": "19.0.1.0.0",
    "author": "quick-sort@outlook.com",
    "website": "quick-sort@outlook.com",
    "license": "LGPL-3",
    "category": "Productivity",
    "depends": ["base", "component", "queue_job"],
    "data": [
        "security/infohub_security.xml",
        "security/ir.model.access.csv",
        "data/queue_data.xml",
        "data/ir_cron_data.xml",
        "views/infohub_item_views.xml",
        "views/infohub_channel_views.xml",
        "views/infohub_source_views.xml",
        "views/infohub_menus.xml",
    ],
    "installable": True,
    "application": True,
    "auto_install": False,
}
