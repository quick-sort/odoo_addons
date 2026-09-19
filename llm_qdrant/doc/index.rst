==========================================
Qdrant Provider for Odoo LLM
==========================================

High-performance vector database for semantic search at scale.

**Module Type:** 🗄️ Vector Store (High Performance)

Architecture
============

::

    ┌───────────────────────────────────────────────────────────────┐
    │                    Used By (RAG Modules)                      │
    │        ┌───────────────┐           ┌───────────────┐         │
    │        │ llm_knowledge │           │llm_agent  │         │
    │        │   (RAG)       │           │  (with RAG)   │         │
    │        └───────┬───────┘           └───────┬───────┘         │
    └────────────────┼───────────────────────────┼─────────────────┘
                     └─────────────┬─────────────┘
                                   ▼
                  ┌───────────────────────────────────────────┐
                  │             llm_store                     │
                  │        (Vector Store API)                 │
                  └─────────────────────┬─────────────────────┘
                                        │
                                        ▼
                  ┌───────────────────────────────────────────┐
                  │       ★ llm_qdrant (This Module) ★        │
                  │          Qdrant Implementation            │
                  │  🔷 High Performance │ Scalable │ Fast    │
                  └─────────────────────┬─────────────────────┘
                                        │
                                        ▼
                  ┌───────────────────────────────────────────┐
                  │              Qdrant Server                │
                  │           (localhost:6333)                │
                  └───────────────────────────────────────────┘

Installation
============

What to Install
---------------

**For high-performance RAG:**

.. code-block:: bash

    # 1. Start Qdrant server
    docker run -p 6333:6333 qdrant/qdrant

    # 2. Install the Odoo module
    odoo-bin -d your_db -i llm_knowledge,llm_qdrant

Auto-Installed Dependencies
---------------------------

- ``llm`` (core infrastructure)
- ``llm_store`` (vector store abstraction)

Why Choose Qdrant?
------------------

+------------------+-------------------------------+
| Feature          | Qdrant                        |
+==================+===============================+
| **Performance**  | ⚡ Very fast search            |
+------------------+-------------------------------+
| **Scale**        | 📈 Handles millions of vectors|
+------------------+-------------------------------+
| **Filtering**    | 🔍 Advanced payload filtering |
+------------------+-------------------------------+
| **Production**   | ✅ Built for production       |
+------------------+-------------------------------+

Vector Store Comparison
-----------------------

+-------------+--------------+----------------+----------------+
| Feature     | llm_pgvector | llm_qdrant     | llm_chroma     |
+=============+==============+================+================+
| **Server**  | 🐘 PostgreSQL| 🔷 Qdrant      | 🌈 Chroma      |
+-------------+--------------+----------------+----------------+
| **Setup**   | Easy         | Moderate       | Moderate       |
+-------------+--------------+----------------+----------------+
| **Scale**   | Medium       | High           | Medium         |
+-------------+--------------+----------------+----------------+
| **Best For**| Simple RAG   | Large scale    | Development    |
+-------------+--------------+----------------+----------------+

Common Setups
-------------

+-------------------------+----------------------------------------------+
| I want to...            | Install                                      |
+=========================+==============================================+
| High-performance RAG    | ``llm_knowledge`` + ``llm_qdrant``           |
+-------------------------+----------------------------------------------+
| Chat + scalable RAG     | ``llm_agent`` + ``llm_openai`` +         |
|                         | ``llm_knowledge`` + ``llm_qdrant``           |
+-------------------------+----------------------------------------------+

Features
========

- Qdrant vector storage
- High-performance similarity search
- Scalable vector operations
- Advanced filtered search support
- Collection management

Configuration
=============

Set up Qdrant server connection in **LLM > Configuration > Vector Stores**:

- **Host**: Qdrant server hostname (e.g., ``localhost``)
- **Port**: Qdrant port (default: ``6333``)
- **API Key**: Authentication key (if required)
- **Collection Name**: Default collection name

Technical Specifications
========================

- **Version**: 18.0.1.0.0
- **License**: LGPL-3
- **Dependencies**: ``llm``, ``llm_store``
- **Python Package**: ``qdrant-client``

Related Modules
===============

- **``llm``** - Core infrastructure
- **``llm_store``** - Vector store abstraction
- **``llm_knowledge``** - RAG implementation
- **``llm_pgvector``** - Alternative: PostgreSQL-native
- **``llm_chroma``** - Alternative: development-friendly

License
=======

LGPL-3

----

*© 2025 Apexive Solutions LLC*
