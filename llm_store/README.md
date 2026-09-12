# LLM Store Base for Odoo

`llm_store` separates a vector-store **service instance** from the isolated
**databases** hosted by that instance.

## Domain model

```text
llm.store (service instance / control plane)
  1 ─── N llm.store.database (physical knowledge database)
              N ─── 1 llm.knowledge.collection (logical source knowledge)
              1 ─── 1 llm.knowledge.vector (build execution compatibility layer)
```

### Store instance — `llm.store`

One record represents a deployment, cluster, server, or SaaS tenant. It owns
the provider type, administrator endpoint, administrator user/secret, and
instance-level metadata. Its administrator identity is responsible for
provisioning child accounts and databases; it is not the logical knowledge
base and does not hold one collection's build settings.

### Store database — `llm.store.database`

One record represents one isolated backend database. Depending on the provider,
that may be implemented as a SQL database/schema/table, Qdrant collection,
Milvus database/collection, search index, namespace, or local directory.

A database:

- belongs to exactly one store instance;
- stores exactly one `llm.knowledge.collection`;
- has optional data-plane endpoint and child-account credentials;
- owns a stable `backend_key` and the physical create/drop lifecycle;
- records one build method: chunkset, embedding model, dimension, and index
  configuration.

A knowledge collection may have many databases. This intentionally supports
building the same documents with different splitters, embedding models,
dimensions, stores, or index parameters and then benchmarking the variants.
One store instance may host databases belonging to many different knowledge
collections.

### Knowledge collection — `llm.knowledge.collection`

A knowledge collection owns source documents and processed Markdown. It is
logical content, not a physical vector database. `database_ids` contains its
independent physical builds; `default_database_id` is only the default retrieval
variant.

### Database build — `llm.knowledge.vector`

This model remains as the execution/search layer used by existing chunk and
retrieval code. It no longer owns or names a backend collection. Every build
belongs to one `llm.store.database`, while the database owns provisioning,
credentials, dimension, and deletion.

## Adapter contract

New providers should implement the database-level methods on
`llm.store.adapter`:

- `provision_database(store, database)`
- `drop_database(store, database)`
- `database_exists(store, database)`
- `insert_database_vectors(...)`
- `delete_database_vectors(...)`
- `search_database_vectors(...)`
- `create_database_index(...)`

The compatibility bridge maps `database.backend_key` to the provider's
collection-oriented `collection_id` argument. Every database receives its own
stable database ID as that key.

Provider adapters that support child accounts or database-specific endpoints
should override the database-level methods and use `database.database_user`,
`database.database_secret`, `database.connection_uri`, and
`database.index_configuration`.

## Lifecycle rules

1. Creating an Odoo database configuration does not immediately create a
   remote resource.
2. `Initialize` provisions the physical database through the instance adapter.
3. `Build` splits and embeds the collection; the first embedding batch may
   infer the dimension before provisioning.
4. `Drop Database` deletes only that physical variant and keeps its Odoo
   configuration reusable.
5. Deleting a provisioned database first performs remote cleanup. Cleanup
   errors block deletion so Odoo does not lose ownership of an orphan resource.
6. A store instance cannot be deleted while it still owns databases.

## Provider-neutral terminology

"Database" is the domain-level isolation boundary, not necessarily a SQL
`DATABASE`. Each provider maps it to its closest independently configurable and
deletable resource.
