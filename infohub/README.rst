InfoHub
=======

Collects news from many places into a single pool.

Two orthogonal notions
----------------------

A **source** is whose the news is — a publisher, e.g. a journal or a news site.
A **channel** is how it is obtained — an RSS feed, an inbound newsletter email,
or a third-party API.

They are deliberately separate. The same publisher may be reachable through
several channels, so an item records both: ``source_id`` says who it belongs
to, ``channel_id`` says how it arrived. An article that reaches us both by RSS
and by newsletter therefore produces two rows differing only by channel.

Channels are pluggable
----------------------

``infohub.channel`` is a ``component`` collection. Each channel addon:

* adds its value to ``channel_type`` with ``selection_add``,
* adds its own configuration fields with ``_inherit`` — the core keeps no
  channel-specific columns, so a new channel never edits the core,
* provides ``infohub.fetch.<type>`` and ``infohub.content.<type>`` components.

Components resolve by **usage suffix**::

    WorkContext(model_name=..., collection=channel).component(
        usage=f"infohub.fetch.{channel.channel_type}")

Usages are unique by construction, so the framework's ambiguous multi-match
path (``SeveralComponentError``) is never reached — no disambiguation predicate
is needed.

Available channels
------------------

==========================  =================================================
``infohub_channel_rss``     RSS / Atom feeds, polled on a schedule
``infohub_channel_email``   Inbound newsletter mail, via a ``mail.alias``
``infohub_channel_mcp``     A tool on a third-party MCP server
==========================  =================================================

Only ``infohub_channel_mcp`` depends on ``llm``. The core does not, so a
deployment that wants only RSS or email never installs the LLM stack.

Models
------

``infohub.source``
    A publisher: name, homepage, and free-form recognition notes.

``infohub.channel``
    How news is obtained. Carries the schedule, an optional ``filter_domain``
    applied to each raw item before it is stored, and per-run health
    (``last_run_at`` / ``error_count`` / ``last_error``).

``infohub.item``
    The pool. Channel, source, time, title, content and link, plus the
    ``external_id`` used for deduplication within a channel and the original
    ``raw_data`` so parsing can be re-run without re-fetching.

Operational notes
-----------------

**Failure bookkeeping uses a separate cursor.** ``error_count`` and
``last_error`` are written on a cursor of their own, because a ``queue_job``
failure rolls the caller's transaction back and would otherwise discard them —
leaving the counter at 0 forever and the auto-disable unable to ever trigger.
Odoo's test ``assertRaises`` rolls back the same way, which is how the bug was
caught.

**Queue channel capacity is configuration, not data.** Fetch jobs go to
``root.infohub``. Capacity lives in ``odoo.conf``::

    [queue_job]
    channels = root:4,root.infohub:2

A missing entry silently falls back to the default, quietly disabling any rate
limiting that depends on it.

**Outbound HTTP is validated.** ``url_guard.py`` enforces the scheme allowlist
and blocks private / loopback / link-local addresses. Redirects are followed
manually so every hop is re-checked; following them automatically would
validate only the first URL.
