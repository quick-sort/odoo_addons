=====================
LLM Odoo User Guides
=====================

Converted Odoo user documentation, contributed as ``llm.tool.guide`` records so
LLM agents can look up how to use the standard Odoo applications (Sales,
Finance, Inventory, HR, …) through the existing ``odoo_model_guide_retriever``
tool.

Content
-------

* ``data/llm_tool_guide_data.xml`` — seed guide records (118), generated from
  the official Odoo 19.0 user documentation. Provided for offline install; the
  runtime sync keeps them current (see below).
* ``data/llm_tool_guide_meta.xml`` — a hand-written meta guide (code
  ``odoo-guides``) explaining how to find a guide among the many records.
* ``rst_renderer.py`` — pure-Python RST→text renderer + adaptive chunking,
  shared by the runtime sync and the offline CLI.

Granularity is adaptive: heavy applications (Finance, Inventory, Sales, HR)
split into many per-topic guides, light ones (Essentials, Studio, Services)
collapse to a couple of guides.

Runtime update
--------------

``llm.odoo.guide.sync`` (Settings → Odoo User Guides) fetches the latest
``odoo/documentation`` tarball from GitHub, renders ``content/applications``,
and upserts ``llm.tool.guide`` records by ``code``. The "Sync from web" button
queues the work on the ``root.llm_odoo_guides`` channel — that channel needs a
capacity entry in ``odoo.conf`` ``[queue_job] channels``, otherwise the job
never runs (silently).

Discovery / retrieval
---------------------

* The ``keyword`` field carries the application name on one guide per app, so
  ``odoo_model_guide_retriever`` lists the 11 applications in its dynamic
  description.
* ``odoo_model_guide_retriever()`` returns a grouped overview,
  ``query="..."`` searches, ``code="..."`` fetches one body.

Offline regeneration
--------------------

Regenerate the seed XML from a local ``odoo/documentation`` checkout::

    ODOO_DOCS=/path/to/content/applications python3 scripts/gen_odoo_guides.py
