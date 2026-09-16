{
    "name": "InfoHub RSS Channel",
    "summary": "Poll RSS and Atom feeds into the InfoHub pool",
    "description": """
InfoHub — RSS / Atom channel
============================

Adds ``rss`` to ``infohub.channel.channel_type`` and polls one feed per channel.

Parsing is generic rather than per-publisher: every child element of
``<item>``/``<entry>`` is kept under its local tag name, so publisher-specific
fields (``prn:industry``, ``dc:creator``, …) stay available to the channel's
``filter_domain`` without special-casing any of them. RSS 2.0, RSS 1.0 (RDF) and
Atom are all handled by locating entries through their local tag names.

Outbound requests follow redirects manually, re-validating every hop with
``infohub.url_guard`` (scheme allowlist, private-range / loopback / link-local
blocking). The body is capped by size, and requests carry a declared feed-reader
User-Agent with a browser fallback, since publishers differ on which they accept.
    """,
    "version": "19.0.1.0.0",
    "author": "quick-sort@outlook.com",
    "website": "quick-sort@outlook.com",
    "license": "LGPL-3",
    "category": "Productivity",
    "depends": ["infohub"],
    "external_dependencies": {"python": ["requests"]},
    "data": [
        "data/queue_data.xml",
        "views/infohub_channel_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
