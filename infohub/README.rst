InfoHub
=======

Collects news from many places into a single pool.

What it is
----------

A **source** is whose the news is — a publisher, e.g. a journal or a news site.
A **channel** is how it is obtained — an RSS feed, an inbound newsletter email,
or a third-party API.

The two are deliberately separate. The same publisher may be reachable through
several channels, so an item records both: ``source_id`` says who it belongs
to, ``channel_id`` says how it arrived.

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
    applied to each raw item before it is stored, and per-run health.

``infohub.item``
    The pooled news item: channel, source, time, title, content and link.

Installation
------------

This addon has no third-party Python dependencies beyond the Odoo base image.

Usage
-----

1. Install a channel addon (RSS / email / MCP).
2. Create a channel record and configure its endpoint.
3. Run a fetch — items land in the shared pool.

Design docs
-----------

The design and acceptance criteria live in ``docs/`` — read them before changing
code:

- ``docs/requirements.md`` — business requirements and boundaries
- ``docs/design.md`` — architecture, models, extension points, rejected options
- ``docs/acceptance.md`` — acceptance criteria (the QC source)
