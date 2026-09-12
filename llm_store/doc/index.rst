========================
LLM Store Architecture
========================

``llm_store`` models two resource levels explicitly:

.. code-block:: text

    llm.store (service instance / administrator control plane)
      1 --- N llm.store.database (isolated physical knowledge database)
                  N --- 1 llm.knowledge.collection (logical source content)
                  1 --- 1 llm.knowledge.vector (build execution layer)

Store instance
==============

``llm.store`` represents one deployment, cluster, server, or SaaS tenant. It
contains the provider service, administrator endpoint and administrator
credentials used to create child accounts and databases. It is not itself a
knowledge database.

Store database
==============

``llm.store.database`` represents one independently configurable physical
knowledge database. A provider may implement it as a database, schema, table,
collection, index, namespace, or directory.

Each database belongs to one store instance and stores exactly one
``llm.knowledge.collection``. It owns its backend key, optional child account,
data-plane connection, chunking configuration, embedding model, dimension,
index configuration, and provision/drop lifecycle.

Knowledge collection
====================

``llm.knowledge.collection`` owns source documents. One collection may have
many databases, each built with a different import and indexing method. This is
how retrieval quality, latency, build cost and storage cost can be compared
without mixing methods in one physical database. One instance may host
databases from many knowledge collections.

Adapter compatibility
=====================

The primary adapter API is database-oriented:

.. code-block:: python

    provision_database(store, database)
    drop_database(store, database)
    database_exists(store, database)
    insert_database_vectors(store, database, vectors, metadata, ids)
    delete_database_vectors(store, database, ids)
    search_database_vectors(store, database, query_vector, limit, filter)
    create_database_index(store, database, index_type)

Default implementations bridge to the collection-oriented provider methods
using ``database.backend_key``. This keeps provider adapters independent from
Odoo build-record IDs while new providers can implement native database
provisioning and database-level credentials directly.

Lifecycle invariants
====================

- A database stores one and only one logical knowledge collection.
- A knowledge collection may own multiple independent database variants.
- A database records one chunking/embedding/index method.
- Only the database owns the backend create/drop lifecycle.
- Build records never delete backend resources independently.
- Remote cleanup failure blocks deletion of the owning Odoo database record.
- A store instance cannot be deleted while databases still reference it.
