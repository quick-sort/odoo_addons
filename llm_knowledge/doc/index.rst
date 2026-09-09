=============
LLM Knowledge
=============

``llm_knowledge`` provides native file and URL documents for Odoo RAG
workflows. Every ``llm.document`` belongs to one collection and follows a
binary retrieval → Markdown extraction lifecycle. HTTP retrieval is built in.

Architecture
============

::

   llm.knowledge.collection
   └── document_ids → llm.document
       ├── retrieve() → binary envelope
       ├── extract() → Markdown
       └── process_document() → retrieve + extract

Extractor routing is implemented by ``llm.document.extractor`` and
``llm.document.extractor.mapping``. Collection mappings have priority over
global mappings. Matching priority is exact MIME, exact extension, MIME
wildcard, then a blank default.

Cache artifacts live below
``collections/<collection_id>/documents/<document_id>/``. No legacy model
alias or cache-path fallback is provided.

Installation
============

Install the ``requests`` Python package, then install the addon:

.. code-block:: bash

   python3 -m pip install requests
   odoo-bin -d your_database -i llm_knowledge

Optional extractor addons
=========================

+-------------------------+----------------------------------------------+
| Capability              | Addon                                        |
+=========================+==============================================+
| Local file extraction   | ``llm_knowledge_extractor_markitdown``       |
+-------------------------+----------------------------------------------+
| Web article extraction  | ``llm_knowledge_extractor_trafilatura``      |
+-------------------------+----------------------------------------------+
| MinerU service          | ``llm_knowledge_extractor_mineru``           |
+-------------------------+----------------------------------------------+

Deprecated parser addons remain disabled and are not part of this pipeline.

HTTP retrieval security
=======================

Native retrieval accepts absolute HTTP and HTTPS URLs, follows at most five
redirects, uses 10-second connect and 60-second read timeouts, and limits each
response to 50 MiB. URL resolution and the connected peer are checked against
private and other restricted address ranges on every redirect. Proxy
environment variables are ignored.

Private destinations are blocked by default. The system parameter
``llm_knowledge.allow_private_urls=True`` relaxes this globally and should only
be used in trusted deployments. Normal processing reuses the cached binary;
force refresh sends stored ETag and Last-Modified validators.

Configuration
=============

Create an active extractor host and a MIME or extension mapping:

.. code-block:: python

   extractor = env["llm.document.extractor"].create({
       "name": "Web pages",
       "extractor_type": "trafilatura",
   })
   env["llm.document.extractor.mapping"].create({
       "name": "HTML",
       "mimetype": "text/html",
       "extractor_id": extractor.id,
   })
   document = env["llm.document"].create({
       "name": "Odoo documentation",
       "collection_id": collection.id,
       "source_type": "url",
       "source_url": "https://www.odoo.com/documentation/19.0/",
   })
   document.process_document()

The upload wizard creates native file/URL documents. Source storage scans
create documents for new files and flag missing files ``to_delete``.

Extension contract
==================

Extractor extensions inherit ``llm.document.extractor.component``, define a
unique ``_usage``, and implement ``extract(envelope)`` returning Markdown
``str``. They extend the extractor host's ``extractor_type`` selection and
provide mapping guidance for their supported MIME types or extensions.

Chunking, embedding, and vector search are provided by downstream addons such
as ``llm_store`` and ``llm_knowledge_pgvector``. This development branch does
not provide database migration, old aliases, old cache fallback, or old vector
payload compatibility; rebuild vector indexes after deployment.
