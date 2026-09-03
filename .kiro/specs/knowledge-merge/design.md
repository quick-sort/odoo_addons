# Merge Plan: knowledge_base_* → llm_knowledge / llm_store

Status: plan approved with corrections (see "Corrections" section), implementation not started.
Last updated: 2026-09-02

## Feature requirements (from user)

1. Knowledge base source documents are stored externally in different storage backends (S3, NAS, local filesystem) — pluggable per KB.
2. One knowledge base can have multiple vector stores, with different chunk sizes, different embedding methods (raw title+content vs. wrapping with context / contextual retrieval), and different embedding models with different dimensions (including models with variable dimensions).
3. Markdown extracted from source files is a managed artifact of the knowledge base — it can be stored in a different place than the source file, but is tracked/managed by the knowledge base record.

## Current state (verified from code, addons in /Users/rui/workspace/odoo-projects/odoo_addons)

Two independent, incompatible stacks solve overlapping problems.

### `llm_knowledge` / `llm_store` stack (mature LLM/provider integration, weak KB modeling)

- `llm.resource` (`llm_knowledge/models/llm_resource.py`) — polymorphic over any Odoo record (`model_id`+`res_id`), pipeline `draft→retrieved→parsed→chunked→ready`, content stored **inline as Text** in the DB. No file/backend concept at all.
- `llm.knowledge.collection` (`llm_knowledge/models/llm_knowledge_collection.py`) `_inherit`s `llm.store.collection`, giving it exactly **one** `store_id` + **one** `embedding_model_id` + one set of default chunk settings (`default_chunk_size`/`default_chunk_overlap`/`default_chunker`/`default_parser`). Hard 1:1:1 coupling — a collection *is* a store config, not a container that can hold several.
- `llm.knowledge.chunk` (`llm_knowledge/models/llm_knowledge_chunk.py`) — `content` is inline required `Text`; chunks belong to a `resource_id` only (no chunkset/config dimension), so two different chunk sizes for the same resource can't coexist. Has a clever virtual `embedding` field (`store=False`, `search="_search_embedding"`) that hijacks Odoo's `search()` domain parser to run vector search transparently — this mechanism should be preserved.
- `llm.store` (`llm_store/models/llm_store.py`) + `llm.store.collection` (abstract, `llm_store/models/llm_store_collection.py`) + `llm.store.adapter` component contract (`llm_store/components/llm_store_adapter.py`) — solid, mandatory-contract, component-adapter pattern. `llm_pgvector` (external Postgres), `llm_qdrant` (Qdrant), `llm_knowledge_pgvector` (`pgvector_local` — embeddings inside Odoo's own DB via `base_pgvector`'s `PgVector` field type) are its adapters. The `pgvector_local` adapter already has real dimension-ceiling handling (`vector` type ≤2000 dims → `halfvec` ≤4000 dims → no ANN index beyond that, via partial indexes per `embedding_model_id`) — the best existing reference for variable/large embedding dimensions. Its own header comment reads `TODO, DEFERRED TO THE llm_knowledge REWORK`, i.e. this exact rework was already anticipated.
- **Key point re: llm_store's role** — confirmed by user: `llm.store` is meant to manage the *operations* of embedding/insert/search dispatch. It is NOT itself a data store for chunk text. Whatever text needs to live "in the vector store" must be passed as payload/metadata alongside the vector through `insert_vectors(vectors, metadata, ids=...)`, and the concrete adapter (pgvector table's `payload jsonb` column, Qdrant point payload, etc.) is what actually persists it.

### `knowledge_base` stack (already implements most of what's requested, weaker LLM integration)

- `knowledge.base` (`knowledge_base/models/knowledge_base.py`) has `md_backend_id` → `storage.backend` (OCA-style addon, already gives filesystem/S3/SFTP/FTP via `selection_add`, with path-traversal protection and gzip transparency). Source files go through `one_storage`'s `one.storage.entry`, itself backed by the same `storage.backend`. **Requirement 1 solved.**
- `knowledge.chunkset` (`knowledge_base_vector_store/models/knowledge_chunkset.py`, N per KB, each with its own `splitter_id` → chunk size/overlap/strategy) → `knowledge.vector` (`knowledge_base_vector_store/models/knowledge_vector.py`, N per chunkset, each with `model_id` + `vector_store_id` + explicit `vector_size`). **Requirement 2's shape is solved** — except contextual-retrieval wrapping vs. raw content is NOT implemented anywhere in either stack today; it's genuinely new work, but per user correction it should be modeled as a splitter variant, not a chunkset field.
- `knowledge.source._extract()` (`knowledge_base/models/knowledge_source.py:139-159`) writes markdown to `kb_id.md_backend_id` at `"<source.id>/content.md"`, decoupled from the source file's own backend (`entry_id`). **Requirement 3 solved.**
- `knowledge.extractor` + component pattern (`knowledge_base/models/knowledge_extractor.py`, `components/knowledge_extractor_component.py`) — polymorphic host, `_get_adapter()` resolves by `usage=extractor_type`. `knowledge_base_markitdown` and `knowledge_base_mineru` are its adapters (MinerU outputs JSON, not markdown — `_output_format="json"`). `knowledge_base_url_fetcher`'s `trafilatura` adapter handles URL-type sources.
- Weaknesses: `knowledge.vector.store`/`knowledge_base_pgvector`/`knowledge_base_qdrant` are thinner duplicates of `llm_store`'s adapters (no metric choice, no orphan-vector handling, no dimension-ceiling handling); no automation/event-driven sync layer; chunk text in this stack is stored as files on `md_backend_id` (`"<source>/chunks/<chunkset>/<seq>.md"`) — this is now superseded by the user's correction (chunk text should live in the vector store, not on a backend file or in Odoo DB).

### storage_backend / one_storage (verified correct, no changes needed)

- `storage.backend` (`storage_backend/models/storage_backend.py`) — component-adapter dispatch (`_get_adapter()` by `backend_type`), uniform API: `open(path, mode)`, `list_files`, `find_files`, `move_files`, `rename`, `rmdir`, `file_exists`, `get_size`, `stat`, `delete`. Path-traversal protected (`_check_relative_path`). Backend types: `filesystem` (built-in), `amazon_s3` (`storage_backend_s3`), `sftp`/`ftp` (`storage_backend_sftp`/`storage_backend_ftp`) — S3/NAS/local all already supported.
- `one_storage`'s `one.storage.entry` — a stable, browsable many2one handle to a file living on a `storage.backend`; mirrors backend contents into a persistent tree. Used for **source files** where a browsable UI matters. Not needed for programmatically-derived paths (extracted markdown), which `knowledge_base` correctly addresses via a bare `md_backend_id` + computed path, no `one_storage` layer.

## Corrections from user (2026-09-02) — supersede parts of the original plan

1. **Drop `markdown_backend_id` per-resource override field on `llm.resource`.** Over-designed. Use only the collection-level `md_backend_id` (one backend per knowledge base/collection, shared by all its resources' extracted markdown). No per-resource override field.

2. **Model contextual-retrieval wrapping as a splitter variant, not a chunkset attribute.** Instead of an `embedding_strategy` selection (`raw`/`contextual`) on `llm.knowledge.chunkset`, follow the same polymorphic component-dispatch pattern already used for extractors and splitters: `llm.knowledge.splitter` (polymorphic host, `_inherit=["collection.base"]`, analogous to `knowledge.splitter`) has a `splitter_type` selection populated via `selection_add` by sibling addons — e.g. `recursive`, `token`, and a new `contextual` splitter type. The `contextual` splitter is a `llm.knowledge.splitter.component` adapter that wraps each chunk with surrounding document context (title, preceding/following text, or an LLM-generated summary) before returning chunk text — it's just another `split(text)` implementation, structurally identical to `recursive`/`token`, not a special-cased field elsewhere. This keeps "different embedding methods" (raw vs. contextual) as a pure splitter-level concern, consistent with "different chunk sizes" also being a splitter-level concern (`chunk_size`/`chunk_overlap` fields already on the splitter host).

3. **Chunk content must NOT be stored in Odoo's database, and must NOT be stored as a file on `md_backend_id` either. It must be stored inside the vector store itself, alongside the vector (as payload/metadata).** Rationale (user's own words): `llm_store` exists to manage the *operations* of embedding (dispatch to embed/insert/search), not to be a vector store in itself — the actual vector store (pgvector table, Qdrant collection, etc.) is the data owner, and chunk text belongs there as payload next to its embedding, not duplicated elsewhere in Odoo. Concretely:
   - `llm.knowledge.chunk` in Odoo becomes a **lightweight pointer/metadata row only**: `resource_id`, `chunkset_id`, `sequence` — no `content` Text field, no backend file path field either.
   - Chunk text is produced transiently in memory during chunking (split → text), passed straight into embedding, and written into the vector store's payload (pgvector's `payload jsonb` column, Qdrant's point payload, etc.) via `insert_vectors(vectors, metadata=[{"text": ..., "resource_id":..., "chunk_id":..., "sequence":...}, ...], ids=chunk_ids)` — no intermediate persistence step in Odoo DB or on a storage backend.
   - Retrieval/search reads chunk text back **from the vector store's search result payload** (`search_vectors()` result already carries `metadata`/`payload` per hit) — not from Odoo DB, not from a backend file.
   - Consequence: chunk text is duplicated once per `llm.knowledge.vector` (chunkset × embedding model × store combination), which is correct — different chunksets may split/wrap text differently (raw vs. contextual), and each needs its own copy stored with its own embedding.
   - This removes the file-based chunk storage (`"<source>/chunks/<chunkset>/<seq>.md"`) pattern from `knowledge_base_vector_store` entirely — it does not carry over to the merged design.
   - `md_backend_id` on the collection is now used **only** for the extracted markdown of resources (requirement 3), not for chunks.

## Target architecture (updated per corrections)

```
llm.knowledge.collection  ("Knowledge Base")
  ├─ md_backend_id → storage.backend                    [req 1, 3] (markdown only, no per-resource override)
  ├─ resource_ids → llm.resource (N)
  │     ├─ source_type: record | file | url
  │     ├─ entry_id → one.storage.entry                  (file sources, via one_storage)   [req 1]
  │     ├─ url                                           (url sources)
  │     └─ content_path (computed, on collection_id.md_backend_id)                          [req 3]
  ├─ chunkset_ids → llm.knowledge.chunkset (N)            [req 2]
  │     ├─ splitter_id → llm.knowledge.splitter (polymorphic: recursive | token | contextual)  [req 2, correction 2]
  │     │     ├─ chunk_size, chunk_overlap
  │     │     └─ splitter_type dispatch → llm.knowledge.splitter.component.split(text)
  │     └─ chunk_ids → llm.knowledge.chunk (pointer-only: resource_id, chunkset_id, sequence — NO content field)  [correction 3]
  └─ vector_ids (via chunkset) → llm.knowledge.vector (N per chunkset)   [req 2]
        ├─ embedding_model_id → llm.model (variable dimension support)
        ├─ store_id → llm.store (pgvector / pgvector_local / qdrant) — ops dispatcher only
        ├─ vector_size (explicit, per-vector, supports variable dims)
        └─ chunk text lives in store_id's payload alongside each vector, not in Odoo   [correction 3]
```

`llm.knowledge.vector` should `_inherit = ["llm.store.collection"]` to reuse `store_id`/`dimension`/`insert_vectors`/`search_vectors`/`delete_vectors` from the existing abstract base, just relocated to the right granularity (per chunkset, not per top-level collection).

## Phased implementation plan

### Phase 0 — Decisions (mostly resolved by corrections above; remaining open items below)

Remaining open items to confirm before/while implementing:
- Exact contextual-splitter design: what context gets wrapped in (static template referencing resource title? preceding/following chunk text? LLM-generated per-chunk summary?). This determines the `contextual` splitter component's implementation, not just its existence as a `splitter_type`.
- Whether `llm.resource` keeps polymorphic `model_id`/`res_id` (arbitrary DB record) support alongside new `file`/`url` source types — recommend yes, add `source_type` rather than replacing the resource model, since `llm_knowledge_automation`'s event-driven sync depends on treating arbitrary Odoo records as resources.
- MinerU's `_output_format="json"` (structured, not markdown) needs a JSON→text normalization step before splitting, same as `knowledge_chunkset._chunk_source()` already does today — decide where that conversion lives (parser adapter itself, vs. a shared step in `llm_resource_parser.py`).

### Phase 1 — Storage layer for source files and markdown (foundation)

- Add `storage_backend`, `one_storage` to `llm_knowledge/__manifest__.py` depends.
- Add to `llm.knowledge.collection`: `md_backend_id` (M2O `storage.backend`, required) — ported from `knowledge_base/models/knowledge_base.py:44-50`.
- Add to `llm.resource`: `source_type` (Selection `record`/`file`/`url`, default `record` for backward compatibility), `entry_id` (M2O `one.storage.entry`, for `file` type), `url` (Char, for `url` type — reconcile with any existing field in `llm_resource_http.py`), `content_path` (computed `"<resource.id>/content.md"` on `collection_id.md_backend_id`).
- Port `knowledge.extractor`'s component-adapter pattern into `llm.resource.parser` component adapters, replacing/extending `llm_resource_parser.py`'s current hardcoded logic. Migrate `knowledge_base_markitdown` and `knowledge_base_mineru` components with minimal changes (they're independent of the KB model). Migrate `knowledge_base_url_fetcher`'s `trafilatura` adapter for `source_type="url"` resources.
- After retrieval+parsing, write markdown to `md_backend_id.open(content_path, "wb")` instead of only setting `content` inline; decide whether to keep inline `content` as a transitional cache or cut over directly (recommend cutting over directly per correction 3's spirit — don't duplicate data in Odoo DB when a backend already owns it).

**Verification**: create a collection with `md_backend_id` pointing to a filesystem backend, add a file resource, run retrieve/parse, confirm `content.md` appears at the expected path under the backend, confirm read-back works.

### Phase 2 — Splitter layer (polymorphic, per correction 2)

- New model `llm.knowledge.splitter` (`_inherit=["collection.base"]`, polymorphic host like `knowledge.splitter`/`knowledge.extractor`): fields `name`, `splitter_type` (Selection, dynamically built from `_get_available_splitters()`, extended via `selection_add`), `chunk_size` (Integer), `chunk_overlap` (Integer), `_get_adapter()` resolving a component by `usage=splitter_type`.
- New component base `llm.knowledge.splitter.component` (`AbstractComponent`, `_collection="llm.knowledge.splitter"`), abstract `split(text) -> list[str]`.
- Port `recursive` and `token` splitter components from `knowledge_base_vector_store/components/recursive_splitter.py` and `token_splitter.py` with minimal changes.
- New `contextual` splitter component — new work (per Phase 0 open item): wraps each chunk with document/context info before returning it as the "chunk text" that will later be embedded. Needs its own design pass on what "context" means here.

### Phase 3 — Chunkset / multi-vector layer (core of requirement 2)

- New model `llm.knowledge.chunkset`: `collection_id` (M2O `llm.knowledge.collection`, cascade), `splitter_id` (M2O `llm.knowledge.splitter`, restrict), `state` (draft/chunking/chunked/error), `chunk_ids` (O2M).
  - `_chunk_source(resource)`: read `resource.content_path` from `collection_id.md_backend_id`, call `splitter_id._get_adapter().split(text)`, create `llm.knowledge.chunk` pointer rows (no text stored) for each resulting piece, **keep the split text in memory** to hand off to the vectorization step (Phase 3 vector build) rather than persisting it anywhere in Odoo.
- Extend `llm.knowledge.chunk`: add `chunkset_id` (M2O, required, cascade), unique constraint `(chunkset_id, resource_id, sequence)`. **Remove/repurpose the `content` field** — per correction 3, chunk text is not stored in Odoo. If a `content` field is kept at all, it should be a non-stored, on-demand computed field that reads back from the vector store's payload via the chunk's primary vector, purely for UI convenience — not the system of record.
- New model `llm.knowledge.vector` (`_inherit=["llm.store.collection"]`): `chunkset_id` (M2O, required, cascade), `embedding_model_id` (M2O `llm.model`, domain `model_use='embedding'`, required), `vector_size` (Integer, required, explicit — enables variable/multiple dimensions per KB), `state` (draft/building/vectorized/error). Reuses inherited `store_id`/`dimension`/`insert_vectors`/`search_vectors`/`delete_vectors` from `llm.store.collection`.
  - `_vectorize()`: for each resource in the chunkset's collection, get chunk texts from the **in-memory/transient split step** (Phase 3's `_chunk_source`) — meaning chunking and vectorization for a given chunkset are likely best implemented as one combined job per resource (split → embed → insert with text-in-payload) rather than two decoupled persisted stages, since the text has nowhere to live in between if not persisted in Odoo. This is a meaningful pipeline design implication of correction 3 worth confirming: **either (a) fuse chunk+vectorize into a single job per (resource, chunkset, vector) with no intermediate persistence, or (b) allow chunk splitting to persist text transiently in a queue_job's own payload/cache until vectorization consumes it.** Recommend (a) for simplicity — chunk rows still get created (as pointers) at the point the vector build actually happens, in the same transaction/job that embeds and inserts.
  - `insert_vectors(vectors, metadata=[{"text": chunk_text, "resource_id":..., "chunk_id":..., "sequence":...}, ...], ids=chunk_ids)` — text travels as payload, persisted by the concrete adapter (pgvector `payload jsonb`, Qdrant point payload).
- Update `llm.knowledge.collection`: remove `_inherit = ["llm.store.collection", ...]` and direct `store_id`/`embedding_model_id`/`dimension` fields; replace with `chunkset_ids` O2M and computed rollups. `default_chunk_size`/`default_chunk_overlap`/`default_chunker`/`default_parser` remain as UI defaults for creating a new chunkset's splitter, not authoritative config.

### Phase 4 — Vector search integration

- `llm.knowledge.chunk.search()`'s custom domain-parsing override (`llm_knowledge/models/llm_knowledge_chunk.py`) must resolve `llm.knowledge.vector` records (via `collection.chunkset_ids.vector_ids`) instead of collections directly, dispatching `search_vectors()` per vector. Aggregation/sorting logic is unchanged in shape.
- Chunk text in search results comes from the vector store's returned payload (already the shape `search_vectors()` returns — `{"id","score","payload"/"metadata"}`) — no separate read-back step needed since text now lives exactly where the search result payload already points.
- Decide default vector-selection policy for searches that don't specify a chunkset/vector explicitly (e.g. an `is_default` boolean on `llm.knowledge.vector`).

### Phase 5 — Data migration for existing installs

Migration script for each existing `llm.knowledge.collection`:
1. Create one `llm.knowledge.chunkset` with a splitter matching the collection's old `default_chunk_size`/`default_chunk_overlap`/`default_chunker`.
2. Create one `llm.knowledge.vector` using the collection's old `store_id`/`embedding_model_id`/`dimension`.
3. Existing `llm.knowledge.chunk` rows: since chunk text was previously stored inline in Odoo (`content` Text field) and per correction 3 that's no longer the system of record, the migration needs to either (a) push existing chunk text into the vector store's payload retroactively (re-upsert with `insert_vectors` including text in metadata) before dropping the `content` column, or (b) leave old `content` data in place as a one-time migration aid and only enforce "no content storage" for newly created chunks going forward. Recommend (a) for consistency, run as a one-time backfill job per collection.
4. No re-embedding needed — same `store_id`, same chunk ids, same vectors; only the payload gains a `text` field it may not have had before.

### Phase 6 — Deprecate `knowledge_base_*` addons

Retire (uninstall/archive, don't hard-delete data on production installs) once ported and verified: `knowledge_base`, `knowledge_base_vector_store`, `knowledge_base_pgvector`, `knowledge_base_qdrant`, `knowledge_base_markitdown`, `knowledge_base_mineru`, `knowledge_base_url_fetcher`.

Keep unchanged (already correct, reused as-is): `storage_backend`, `storage_backend_s3`, `storage_backend_sftp`, `storage_backend_ftp`, `one_storage`, `llm_store`, `llm_pgvector`, `llm_qdrant`, `llm_knowledge_pgvector` (adapters unchanged; `llm.knowledge.collection`'s relationship to them changes from direct inheritance to indirect via `llm.knowledge.vector`). `llm_knowledge_automation` needs no change beyond following field renames on `llm.knowledge.collection` if `sync_resources()`/`domain_ids` references shift.

## Key files referenced during investigation (for quick re-orientation next session)

- `knowledge_base/models/knowledge_base.py` — `knowledge.base` model, `md_backend_id`, extraction workflow.
- `knowledge_base/models/knowledge_source.py` — `knowledge.source`, `_extract()`, `content_path` pattern.
- `knowledge_base/models/knowledge_extractor.py` + `knowledge_base/components/knowledge_extractor_component.py` — polymorphic extractor pattern to port.
- `knowledge_base_vector_store/models/knowledge_chunkset.py`, `knowledge_vector.py`, `knowledge_splitter.py` — chunkset/vector/splitter pattern (chunk file-storage part is superseded by correction 3; splitter/chunkset/vector shape is still the reference).
- `knowledge_base_vector_store/components/recursive_splitter.py`, `token_splitter.py` — splitter components to port as-is.
- `knowledge_base_markitdown/components/markitdown_extractor.py`, `knowledge_base_mineru/components/mineru_extractor.py`, `knowledge_base_url_fetcher/components/trafilatura_extractor.py` — extractor components to port.
- `llm_store/models/llm_store.py`, `llm_store_collection.py`, `llm_store/components/llm_store_adapter.py` — the ops-dispatch abstraction to keep and reuse at the `llm.knowledge.vector` level.
- `llm_pgvector/components/pgvector_store_adapter.py`, `llm_qdrant/components/qdrant_store_adapter.py`, `llm_knowledge_pgvector/components/pgvector_local_store_adapter.py` — adapters, unchanged; note `pgvector_local`'s dimension-ceiling handling (vector ≤2000 dims / halfvec ≤4000 dims / no ANN index beyond that) as the reference for variable-dimension handling.
- `llm_knowledge/models/llm_resource.py`, `llm_resource_chunker.py`, `llm_resource_parser.py`, `llm_resource_retriever.py`, `llm_resource_http.py` — current resource pipeline to extend with `source_type`/`entry_id`/`content_path`.
- `llm_knowledge/models/llm_knowledge_chunk.py` — chunk model with the virtual `embedding` field / custom `search()` override (vector-search-via-domain-parsing mechanism) — preserve this mechanism, adapt its collection-resolution step to resolve `llm.knowledge.vector` instead of `llm.knowledge.collection`.
- `llm_knowledge/models/llm_knowledge_collection.py` — current 1:1:1 coupling to break apart into `chunkset_ids`/`vector_ids`.
- `storage_backend/models/storage_backend.py`, `storage_backend/components/base_adapter.py` — storage abstraction, no changes needed.
- `one_storage/models/one_storage_entry.py`, `one_storage/models/storage_backend.py` — file-handle layer for source files, no changes needed.

## Next session starting point

Nothing has been implemented yet. Resume by:
1. Re-confirming the remaining Phase 0 open items (contextual splitter design especially).
2. Starting Phase 1 (storage layer) as the lowest-risk foundation, since later phases depend on `md_backend_id`/`content_path` existing on `llm.knowledge.collection`/`llm.resource`.
