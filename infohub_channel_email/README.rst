InfoHub Email Channel
=====================

Receives newsletter email into the InfoHub pool.

What it does
------------

Adds the ``email`` channel type. Inbound mail arrives at the
``infohub.email.message`` relay through a static ``mail.alias``; which channel an
email belongs to is decided by its recipient address (``channel.email_to``), so
adding a newsletter does not mean adding an alias.

Email is pushed to us, not polled — the channel's ``fetch`` returns nothing.

Installation
------------

Depends on ``infohub`` and ``mail``. No extra Python packages.

Configuration
-------------

1. Create a channel of type *Email* and set its *Receiving Address*.
2. Point a ``fetchmail.server`` at the mailbox (state ``done``). The mail
   module's fetch cron stays inactive until one exists.

Usage
-----

Mail delivered to the alias is parsed into an item and stored on the relay for
later reprocessing.

Design docs
-----------

- ``docs/requirements.md`` — business requirements and boundaries
- ``docs/design.md`` — relay model, alias routing, rejected options
- ``docs/acceptance.md`` — acceptance criteria (the QC source)
