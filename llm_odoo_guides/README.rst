=====================
LLM Odoo User Guides
=====================

Converted Odoo user documentation, contributed as ``llm.tool.guide`` records so
LLM agents can look up how to use the standard Odoo applications (Sales,
Finance, Inventory, HR, …) through the existing ``odoo_model_guide_retriever``
tool.

Content
-------

* ``data/llm_tool_guide_data.xml`` — the guide records. Generated from the
  official Odoo 19.0 user documentation (``content/applications``) with
  ``scripts/gen_odoo_guides.py``.
* ``data/llm_tool_guide_meta.xml`` — a hand-written meta guide (code
  ``odoo-guides``) explaining how to discover and locate a guide among the
  many records.

Granularity is adaptive: heavy applications (Finance, Inventory, Sales, HR)
split into many per-topic guides, light ones (Essentials, Studio, Services)
collapse to a couple of guides.

Discovery / retrieval
---------------------

* The ``keyword`` field carries the application name (``sales``, ``finance``,
  …) on one guide per application, so ``odoo_model_guide_retriever`` lists the
  11 applications in its dynamic description.
* ``odoo_model_guide_retriever()`` returns a grouped overview (one line per
  application), ``query="..."`` searches the index, and ``code="..."`` fetches
  one guide's body.

Regenerating
------------

The XML is data-only and loaded with ``noupdate="0"`` so the records are
re-imported on every addon upgrade. To regenerate from a fresh checkout of
``odoo/documentation``::

    python3 scripts/gen_odoo_guides.py

See ``scripts/gen_odoo_guides.py`` for the RST→text renderer and the adaptive
chunking rules.
