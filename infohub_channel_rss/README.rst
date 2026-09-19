InfoHub RSS Channel
===================

Polls RSS and Atom feeds into the InfoHub pool.

What it does
------------

Adds the ``rss`` channel type. One channel polls exactly one feed — several feeds
mean several channels, each with its own schedule and item filter.

Parsing is generic rather than per-publisher: every child element of
``<item>``/``<entry>`` is kept under its local tag name, so publisher-specific
fields (``prn:industry``, ``dc:creator``, …) stay available to ``filter_domain``
without special-casing any of them. RSS 2.0, RSS 1.0 (RDF) and Atom are all
handled.

Installation
------------

``external_dependencies``: ``requests`` (already in the Odoo base image). No
additional Python packages to install.

Configuration
-------------

Create a channel of type *RSS / Atom* and set its *Feed URL*.

Usage
-----

Enable *Auto Fetch*, or press *Fetch Now*. Items land in the shared pool.

Design docs
-----------

- ``docs/requirements.md`` — business requirements and boundaries
- ``docs/design.md`` — parsing approach, SSRF handling, rejected options
- ``docs/acceptance.md`` — acceptance criteria (the QC source)
