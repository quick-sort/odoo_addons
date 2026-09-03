"""Migrate pre-2.0 llm_knowledge data to the chunkset/vector model.

Before this version, ``llm.knowledge.collection`` directly inherited
``llm.store.collection`` (one ``store_id`` + one ``embedding_model_id`` per
collection) and ``llm.knowledge.chunk`` stored its text inline in a
``content`` column. This version introduces ``llm.knowledge.chunkset``
(splitter/chunk-size configuration, table ``llm_knowledge_chunkset``) and
``llm.knowledge.vector`` (embedding model + store configuration, table
``llm_knowledge_vector``), allowing several of each per collection, and adds
a required ``chunkset_id`` column on ``llm_knowledge_chunk`` while dropping
its ``content`` column (chunk text now lives in the vector store's payload,
alongside the embedding, per the merge design's storage decision -- see
.kiro/specs/knowledge-merge/design.md, correction 3).

This runs as a *pre*-migrate script (before Odoo's ``_auto_init`` syncs the
new schema) and therefore only uses raw SQL: at this point the new
``llm.knowledge.chunkset``/``llm.knowledge.vector`` models and the new
``llm_knowledge_chunk.chunkset_id`` column do not exist as ORM-visible
fields yet, but we can create the tables/columns ourselves so that by the
time ``_auto_init`` runs, every existing chunk row already has a non-NULL
``chunkset_id`` and the NOT NULL constraint Odoo will try to add for the
new ``required=True`` field does not fail.

Vectors that already exist in an external store are left untouched (same
``store_id``, same chunk ids) -- no re-embedding happens here. The store
payload just won't carry a "text" key for chunks embedded before this
migration until an administrator reruns ``action_build`` on the affected
vector, which re-splits/re-embeds/upserts with text going forward.
"""

import logging

_logger = logging.getLogger(__name__)


def _table_exists(cr, table):
    cr.execute(
        "SELECT 1 FROM information_schema.tables WHERE table_name = %s", (table,)
    )
    return bool(cr.fetchone())


def _column_exists(cr, table, column):
    cr.execute(
        """
        SELECT 1 FROM information_schema.columns
        WHERE table_name = %s AND column_name = %s
        """,
        (table, column),
    )
    return bool(cr.fetchone())


def migrate(cr, version):
    if not version:
        return
    if not _table_exists(cr, "llm_knowledge_collection"):
        return
    if not _column_exists(cr, "llm_knowledge_collection", "store_id"):
        # Already migrated (store_id/embedding_model_id moved to
        # llm_knowledge_vector) or a fresh install: nothing to do.
        return

    _ensure_new_tables(cr)
    _backfill_chunksets_and_vectors(cr)
    _drop_obsolete_columns(cr)


def _ensure_new_tables(cr):
    """Create the new tables/columns ahead of _auto_init so we can backfill
    chunkset_id before Odoo tries to enforce NOT NULL on it."""
    cr.execute(
        """
        CREATE TABLE IF NOT EXISTS llm_knowledge_splitter (
            id serial PRIMARY KEY,
            name varchar NOT NULL,
            splitter_type varchar NOT NULL DEFAULT 'recursive',
            active boolean DEFAULT true,
            chunk_size integer DEFAULT 500,
            chunk_overlap integer DEFAULT 50,
            context_model_id integer,
            create_uid integer, create_date timestamp,
            write_uid integer, write_date timestamp
        )
        """
    )
    cr.execute(
        """
        CREATE TABLE IF NOT EXISTS llm_knowledge_chunkset (
            id serial PRIMARY KEY,
            name varchar NOT NULL,
            sequence integer DEFAULT 10,
            collection_id integer NOT NULL
                REFERENCES llm_knowledge_collection(id) ON DELETE CASCADE,
            splitter_id integer NOT NULL
                REFERENCES llm_knowledge_splitter(id) ON DELETE RESTRICT,
            is_default boolean DEFAULT false,
            active boolean DEFAULT true,
            state varchar DEFAULT 'draft',
            create_uid integer, create_date timestamp,
            write_uid integer, write_date timestamp
        )
        """
    )
    cr.execute(
        """
        CREATE TABLE IF NOT EXISTS llm_knowledge_vector (
            id serial PRIMARY KEY,
            name varchar NOT NULL,
            chunkset_id integer NOT NULL
                REFERENCES llm_knowledge_chunkset(id) ON DELETE CASCADE,
            store_id integer REFERENCES llm_store(id) ON DELETE RESTRICT,
            embedding_model_id integer NOT NULL,
            is_default boolean DEFAULT false,
            state varchar DEFAULT 'draft',
            dimension integer,
            vector_count integer,
            metadata jsonb,
            description text,
            active boolean DEFAULT true,
            create_uid integer, create_date timestamp,
            write_uid integer, write_date timestamp
        )
        """
    )
    if not _column_exists(cr, "llm_knowledge_chunk", "chunkset_id"):
        cr.execute(
            """
            ALTER TABLE llm_knowledge_chunk
            ADD COLUMN chunkset_id integer
                REFERENCES llm_knowledge_chunkset(id) ON DELETE CASCADE
            """
        )


def _backfill_chunksets_and_vectors(cr):
    cr.execute(
        """
        SELECT id, name, store_id, embedding_model_id, dimension,
               default_chunk_size, default_chunk_overlap
        FROM llm_knowledge_collection
        """
    )
    collections = cr.fetchall()

    for (
        collection_id,
        name,
        store_id,
        embedding_model_id,
        dimension,
        default_chunk_size,
        default_chunk_overlap,
    ) in collections:
        splitter_name = "%s - Default Splitter" % (name or collection_id)
        cr.execute(
            """
            INSERT INTO llm_knowledge_splitter
                (name, splitter_type, chunk_size, chunk_overlap)
            VALUES (%s, 'recursive', %s, %s)
            RETURNING id
            """,
            (splitter_name, default_chunk_size or 500, default_chunk_overlap or 50),
        )
        splitter_id = cr.fetchone()[0]

        # Existing chunks were already embedded (if any) with content
        # baked in, so mark the default chunkset 'chunked' -- there is
        # nothing pending to (re)split for them.
        cr.execute(
            """
            INSERT INTO llm_knowledge_chunkset
                (name, collection_id, splitter_id, is_default, state)
            VALUES ('Default', %s, %s, true, 'chunked')
            RETURNING id
            """,
            (collection_id, splitter_id),
        )
        chunkset_id = cr.fetchone()[0]

        if embedding_model_id:
            cr.execute(
                """
                INSERT INTO llm_knowledge_vector
                    (name, chunkset_id, store_id, embedding_model_id,
                     is_default, dimension, state)
                VALUES ('Default', %s, %s, %s, true, %s, %s)
                """,
                (
                    chunkset_id,
                    store_id,
                    embedding_model_id,
                    dimension or 0,
                    "vectorized" if store_id else "draft",
                ),
            )
        elif store_id:
            _logger.warning(
                "Collection %s had a store_id but no embedding_model_id; "
                "skipping default vector creation -- configure one manually "
                "after upgrade.",
                collection_id,
            )

        # Re-parent every chunk belonging to a resource of this collection
        # onto the new default chunkset.
        cr.execute(
            """
            UPDATE llm_knowledge_chunk
            SET chunkset_id = %s
            WHERE chunkset_id IS NULL
              AND resource_id IN (
                  SELECT resource_id FROM llm_knowledge_resource_collection_rel
                  WHERE collection_id = %s
              )
            """,
            (chunkset_id, collection_id),
        )

    # Chunks that could not be attributed to any collection (orphaned
    # resource, or a resource in no collection) have no home for the new
    # required chunkset_id and carried no separately-retrievable text once
    # the old content column is dropped below; remove them rather than
    # leave the database unable to satisfy the NOT NULL constraint.
    cr.execute("DELETE FROM llm_knowledge_chunk WHERE chunkset_id IS NULL")
    if cr.rowcount:
        _logger.warning(
            "Deleted %s orphan llm_knowledge_chunk rows with no resolvable "
            "collection/chunkset during migration.",
            cr.rowcount,
        )

    cr.execute("ALTER TABLE llm_knowledge_chunk ALTER COLUMN chunkset_id SET NOT NULL")


def _drop_obsolete_columns(cr):
    # Chunk text (content) is no longer stored in Odoo's database (see
    # module docstring); the old per-resource chunking fields are
    # superseded by llm.knowledge.splitter/chunkset.
    if _column_exists(cr, "llm_knowledge_chunk", "content"):
        cr.execute("ALTER TABLE llm_knowledge_chunk DROP COLUMN content")
    for column in ("chunker", "target_chunk_size", "target_chunk_overlap"):
        if _column_exists(cr, "llm_resource", column):
            cr.execute("ALTER TABLE llm_resource DROP COLUMN %s" % column)  # noqa: S608
    for column in ("store_id", "embedding_model_id", "dimension", "default_chunker"):
        if _column_exists(cr, "llm_knowledge_collection", column):
            cr.execute(
                "ALTER TABLE llm_knowledge_collection DROP COLUMN %s" % column  # noqa: S608
            )
