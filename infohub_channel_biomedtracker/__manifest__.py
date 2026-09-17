{
    "name": "InfoHub BioMedTracker Channel",
    "summary": "Pull BioMedTracker (Citeline) drug-development events into the InfoHub pool",
    "description": """
InfoHub — BioMedTracker channel
===============================

Adds ``biomedtracker`` to ``infohub.channel.channel_type`` and pulls
drug-development event rows from BioMedTracker's advanced event search.

Authentication is a three-step Auth0 handshake against
``auth.norstella.com`` producing a session cookie, which is stored on the
channel and reused until it expires. A manual cookie can be pasted instead,
for accounts that login automation cannot handle. When a fetch comes back
empty-handed the stored session is considered stale and the login re-run once
before giving up.

Rows are de-duplicated upstream: rows sharing Company + Drug + Event Type +
Event Date are merged into one item, differing text fields joined with " / ".
    """,
    "version": "19.0.1.0.0",
    "author": "quick-sort@outlook.com",
    "website": "quick-sort@outlook.com",
    "license": "LGPL-3",
    "category": "Productivity",
    "depends": ["infohub"],
    "external_dependencies": {"python": ["requests"]},
    "data": [
        "views/infohub_channel_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
