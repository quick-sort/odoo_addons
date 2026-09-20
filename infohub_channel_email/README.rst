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

By default a whole email becomes a single item. A newsletter digest can instead
be split into one item per article with the ``infohub_email_splitter`` agent
(opt-in per channel).

Installation
------------

Depends on ``infohub``, ``mail`` and ``infohub_agent`` (which pulls in ``llm``).
No extra Python packages. Splitting also needs an LLM provider addon
(``llm_openai`` or ``llm_anthropic``) and a configured provider record.

Configuration
-------------

1. Create a channel of type *Email* and set its *Receiving Address*.
2. Point a ``fetchmail.server`` at the mailbox (state ``done``). The mail
   module's fetch cron stays inactive until one exists.

Splitting digest emails
-----------------------

1. Enable *Split into Items* on the email channel.
2. Configure the *InfoHub Email Splitter* agent (*LLM ▸ Agents*, code
   ``infohub_email_splitter``): pick a provider and model. Without both, the
   channel falls back to storing the whole email as one item.
3. Inbound mail is then queued (``root.infohub``) and split into one item per
   article. The original email stays on the relay for later reprocessing.

Usage
-----

Mail delivered to the alias is parsed into item(s) and stored on the relay for
later reprocessing.

Design docs
-----------

- ``docs/requirements.md`` — business requirements and boundaries
- ``docs/design.md`` — relay model, alias routing, digest splitting, rejected options
- ``docs/acceptance.md`` — acceptance criteria (the QC source)
