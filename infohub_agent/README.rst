=============
InfoHub Agent
=============

Tag InfoHub news items with a fixed taxonomy, using an LLM agent.

The ``infohub`` core stays free of the LLM stack; this addon owns the
dependency, the same way ``infohub_channel_mcp`` does.

Install
=======

Depends on ``infohub`` and ``llm``. It also needs an LLM provider addon
(``llm_openai`` or ``llm_anthropic``) and a configured provider record.

Setup
=====

1. **Define the taxonomy** under *InfoHub ▸ Settings ▸ Tags*. Each tag needs
   a ``code`` (the identifier the model answers with, e.g. ``clinical``) and a
   ``description`` saying when to apply it — that text is sent to the model
   verbatim, so write it for the model. While the taxonomy is empty, nothing
   happens: items stay pending and no LLM call is made.
2. **Configure the agent.** *LLM ▸ Agents ▸ InfoHub Tagger* (``code``
   ``infohub_tagger``) ships without a provider or model, since those are per
   environment. Pick both, and set the assistant's model under *LLM ▸ Providers*
   first if needed.
3. **Wait for the cron**, *InfoHub: Enqueue item tagging batches* (every 15
   minutes), or run ``env["infohub.item"]._cron_enqueue_tagging()`` by hand.

Items progress through ``tagging_state``: ``pending`` → ``queued`` → ``done``
(tags assigned) or ``skipped`` (the model found no matching tag). A failure
sets ``error`` and records the reason in ``tagging_error``; the *Re-tag*
button on the item form puts a record back in the queue.

How it works
============

A dispatch-only cron claims up to ``TAGGING_BATCH_SIZE * TAGGING_MAX_JOBS_PER_RUN``
(20 × 10) pending items per pass, marks each batch ``queued`` and enqueues one
queue job per batch on the ``root.infohub`` channel (capacity in ``odoo.conf``).
The job sends the taxonomy plus the item **titles** — no bodies — as a single
user message, and parses the JSON answer back into ``tag_ids``. Re-tagging
replaces the previous tags, so the job is idempotent.

Tag storage is a plain many2many (``infohub_item_tag_rel``). Odoo gives the
relation table a ``PRIMARY KEY(item_id, tag_id)`` and an
``INDEX(tag_id, item_id)``, so both "items carrying this tag" and "tags on this
item" are index scans. The taxonomy is small and stable, so that index stays
cheap no matter how many items accumulate — no special indexing is required.

Safety notes
============

* Item titles are untrusted third-party content. The agent carries **no
  tools**, unknown tag codes are dropped, and item ids outside the batch are
  ignored, so the worst an injected instruction can achieve is a wrong tag.
* Installing this addon back-fills every existing item to ``pending``, so the
  first cron passes will tag the whole pool (200 items per pass). On a large
  existing pool, bulk-set ``tagging_state`` to ``done`` first if that is not
  wanted.
* Each batch produces one ``llm.thread`` and its messages — the audit trail of
  what was sent and answered, at roughly one thread per 20 items.
