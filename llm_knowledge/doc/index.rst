==============
LLM Knowledge
==============

``llm_knowledge`` provides dependency-light knowledge collections, resources, and
an extensible extraction lifecycle. Third-party document extraction libraries are
owned by optional addons rather than the core module.

Architecture
============

::

    llm_knowledge
    ├── llm_knowledge_extractor_markitdown
    ├── llm_knowledge_extractor_trafilatura
    ├── llm_knowledge_extractor_mineru
    ├── llm_knowledge_parser_markdownify
    ├── llm_knowledge_parser_pymupdf
    └── llm_knowledge_retriever_http

The extractor addons register OCA components against the
``llm.resource.extractor`` collection. Core owns the abstract component and resource
state transitions. Parser and retriever addons preserve the older record-backed
attachment pipeline without forcing its dependencies on every installation.

Installation
============

Core requires no third-party Python extraction package:

.. code-block:: bash

   odoo-bin -d your_database -i llm_knowledge

Install only the features required by the database:

+----------------------+----------------------------------------------+------------------------+
| Feature              | Odoo addon                                   | Python dependency      |
+======================+==============================================+========================+
| Local file extraction| ``llm_knowledge_extractor_markitdown``       | ``markitdown``         |
+----------------------+----------------------------------------------+------------------------+
| Web extraction       | ``llm_knowledge_extractor_trafilatura``      | ``trafilatura``        |
+----------------------+----------------------------------------------+------------------------+
| MinerU service       | ``llm_knowledge_extractor_mineru``           | ``requests``           |
+----------------------+----------------------------------------------+------------------------+
| Legacy HTML parsing  | ``llm_knowledge_parser_markdownify``         | ``markdownify``        |
+----------------------+----------------------------------------------+------------------------+
| Legacy PDF parsing   | ``llm_knowledge_parser_pymupdf``             | ``pymupdf``/PyMuPDF    |
+----------------------+----------------------------------------------+------------------------+
| Legacy HTTP retrieval| ``llm_knowledge_retriever_http``             | requests, markdownify  |
+----------------------+----------------------------------------------+------------------------+

For example:

.. code-block:: bash

   python3 -m pip install trafilatura
   odoo-bin -d your_database -i llm_knowledge_extractor_trafilatura

Optional addons are not auto-installed. Odoo validates their declared Python imports;
package installation and version locking remain deployment responsibilities.

Extractor configuration
=======================

Installing an extractor addon extends the extractor type selection. Create an active
``llm.resource.extractor`` record for each desired implementation. A URL example:

.. code-block:: python

   extractor = env["llm.resource.extractor"].create({
       "name": "Web pages",
       "extractor_type": "trafilatura",
   })
   resource = env["llm.resource"].create({
       "name": "Odoo documentation",
       "source_type": "url",
       "source_url": "https://www.odoo.com/documentation/19.0/",
       "extractor_id": extractor.id,
       "collection_ids": [(4, collection.id)],
   })
   resource.process_resource()

When no override is selected, core uses the first active installed extractor compatible
with ``source_type``. Stale records whose optional component is absent are skipped.

Core-only behavior
==================

Without optional addons, record-backed plain text, Markdown, JSON, and image references
continue to work. PDF and HTML fields use the generic unsupported-file representation.
Native file and URL resources require a matching extractor addon.

Files and external URLs entered in the upload wizard are created as native file/URL
resources. Uploaded file bytes are copied into ``one.storage``. The legacy HTTP
retriever and record-backed PDF/HTML parsers are needed only for existing resources
that retain the older attachment pipeline.

Upgrade guidance
================

The extractor usage keys ``markitdown``, ``trafilatura``, and ``mineru`` are preserved.
Install the matching optional addons for existing extractor records while upgrading
core. Install the PyMuPDF and Markdownify parser addons to retain legacy attachment
parsing, and install the HTTP retriever addon while legacy HTTP resources remain.

.. code-block:: bash

   odoo-bin -d your_database -u llm_knowledge \
      -i llm_knowledge_extractor_markitdown,llm_knowledge_extractor_trafilatura

Extension contract
==================

Extractor extensions depend on ``llm_knowledge``, inherit
``llm.resource.extractor.component``, define unique ``_usage``, ``_input``, and
``_output_format`` attributes, extend ``extractor_type`` with
``fields.Selection(selection_add=[...])`` plus an ``ondelete`` policy, and declare
only their own external Python dependencies.

Chunking, embedding, and vector search are provided by downstream addons such as
``llm_store`` and ``llm_knowledge_pgvector``.
