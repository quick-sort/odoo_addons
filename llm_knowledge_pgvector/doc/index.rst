==========================================
pgvector Provider for Odoo LLM
==========================================

PostgreSQL-native vector storage using pgvector extension.

**Module Type:** 🗄️ Vector Store (PostgreSQL Native)

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
                  │      ★ llm_pgvector (This Module) ★       │
                  │         pgvector Implementation           │
                  │  🐘 PostgreSQL │ Native │ No Extra Server │
                  └─────────────────────┬─────────────────────┘
                                        │
                                        ▼
                  ┌───────────────────────────────────────────┐
                  │             PostgreSQL + pgvector         │
                  │           (Your Odoo Database)            │
                  └───────────────────────────────────────────┘

Installation
============

What to Install
---------------

**For RAG with PostgreSQL vectors:**

.. code-block:: bash

    # 1. Install pgvector extension on PostgreSQL
    # See: https://github.com/pgvector/pgvector

    # 2. Install the Odoo module
    odoo-bin -d your_db -i llm_knowledge,llm_pgvector

Auto-Installed Dependencies
---------------------------

- ``llm`` (core infrastructure)
- ``llm_store`` (vector store abstraction)

Why Choose pgvector?
--------------------

+------------------+-------------------------------+
| Feature          | pgvector                      |
+==================+===============================+
| **Integration**  | 🐘 Uses your Odoo PostgreSQL  |
+------------------+-------------------------------+
| **Extra Server** | ❌ Not needed                 |
+------------------+-------------------------------+
| **Simplicity**   | ✅ No external dependencies   |
+------------------+-------------------------------+
| **Scale**        | 📊 Good for moderate datasets |
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
| Simple RAG              | ``llm_knowledge`` + ``llm_pgvector``         |
+-------------------------+----------------------------------------------+
| Chat + RAG              | ``llm_agent`` + ``llm_openai`` +         |
|                         | ``llm_knowledge`` + ``llm_pgvector``         |
+-------------------------+----------------------------------------------+

Features
========

- Native PostgreSQL vector storage
- Cosine similarity search
- Collection-specific indices
- Metadata filtering
- Uses existing Odoo database connection

Configuration
=============

1. Ensure pgvector extension is installed on your PostgreSQL server
2. Install the module
3. Configure vector store in **LLM > Configuration > Vector Stores**
4. Set up knowledge base with pgvector as the storage backend

Technical Specifications
========================

- **Version**: 18.0.1.0.0
- **License**: LGPL-3
- **Dependencies**: ``llm``, ``llm_store``
- **Python Packages**: ``pgvector``, ``numpy``

Related Modules
===============

- **``llm``** - Core infrastructure
- **``llm_store``** - Vector store abstraction
- **``llm_knowledge``** - RAG implementation
- **``llm_qdrant``** - Alternative: high-performance Qdrant
- **``llm_chroma``** - Alternative: development-friendly Chroma

License
=======

LGPL-3

----

*© 2025 Apexive Solutions LLC*
