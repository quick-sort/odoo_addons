InfoHub MCP Channel
===================

Pulls news from a third-party MCP tool into the InfoHub pool.

What it does
------------

Adds the ``mcp`` channel type. Calls a tool exposed by an MCP server and ingests
the returned items.

An MCP tool describes nothing about its reply, so results are normalised
defensively — a JSON document is decoded, a list taken as-is, a dict probed for
common envelope keys. Every field the tool returns is preserved in ``raw_data``
for ``filter_domain``.

This is the only InfoHub addon that depends on ``llm``.

Installation
------------

Depends on ``infohub`` and ``llm``. Install ``llm``'s requirements (``mcp``,
``pydantic``, etc.) — see ``llm/requirements.txt``.

Configuration
-------------

1. Create an *LLM > Configuration > MCP Clients* record (endpoint URL + API key).
2. Create a channel of type *MCP / API*, pick that client, and set the *Tool Name*.

Credentials live on the ``llm.mcp.client`` record — the channel only references it.

Design docs
-----------

- ``docs/requirements.md`` — business requirements and boundaries
- ``docs/design.md`` — result normalisation, dependency isolation
- ``docs/acceptance.md`` — acceptance criteria (the QC source)
