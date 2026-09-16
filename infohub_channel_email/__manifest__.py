{
    "name": "InfoHub Email Channel",
    "summary": "Receive newsletter email into the InfoHub pool",
    "description": """
InfoHub — email channel
=======================

Adds ``email`` to ``infohub.channel.channel_type`` and collects newsletters that
arrive by mail.

Inbound mail reaches ``infohub.email.message`` through a ``mail.alias``. The
alias is static: which channel an email belongs to is decided by its recipient
address (``infohub.channel.email_to``), so adding a newsletter does not mean
adding an alias.

``mail.alias`` can only route to a model carrying ``message_ids``, so mail
cannot be delivered straight into ``infohub.item``. The relay model keeps the
pool free of chatter tables — ``mail_message`` / ``mail_followers`` /
``mail_notification`` grow with received emails, not with the number of news
items — and preserves the original message for when a newsletter's layout
changes and parsing needs revisiting.

Delivery additionally requires a ``fetchmail.server`` in state ``done`` pointed
at the mailbox. The mail module's fetch cron stays inactive until one exists.
    """,
    "version": "19.0.1.0.0",
    "author": "quick-sort@outlook.com",
    "website": "quick-sort@outlook.com",
    "license": "LGPL-3",
    "category": "Productivity",
    "depends": ["infohub", "mail"],
    "data": [
        "security/ir.model.access.csv",
        "data/mail_alias.xml",
        "views/infohub_channel_views.xml",
        "views/infohub_email_message_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
