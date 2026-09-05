# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Repository layout

A flat collection of Odoo 19 addons — each top-level directory is one addon (has `__manifest__.py`). There is no build system at repo level; addons are consumed by an Odoo server.

The Odoo runtime is Docker: container `odoo` (image `odoo:19.0`) with the parent directory `~/workspace/odoo-projects` mounted at `/mnt/extra-addons`, so this repo lives at `/mnt/extra-addons/odoo_addons` inside the container. Config: `../odoo.conf` (db `odoo`, Postgres on host, `server_wide_modules = base,web,queue_job`, queue_job channels configured there).

### Commands

```bash
# Install / upgrade addons (always --workers=0 --no-http for one-shot commands)
docker exec odoo odoo -c /etc/odoo/odoo.conf -d <db> -i <addon1>,<addon2> --stop-after-init --workers=0 --no-http
docker exec odoo odoo -c /etc/odoo/odoo.conf -d <db> -u <addon> --stop-after-init --workers=0 --no-http

# Run a module's unit tests
docker exec odoo odoo -c /etc/odoo/odoo.conf -d <db> -i <addon> \
    --test-enable --test-tags /<addon> --stop-after-init --workers=0 --no-http

# Single test class / method
#   --test-tags /<addon>:<TestClass>  or  /<addon>:<TestClass>.<method>

# Interactive / scripted shell
docker exec -i odoo odoo shell -c /etc/odoo/odoo.conf -d <db> --no-http --workers=0 < script.py

# Odoo server logs
docker exec odoo tail -100 /var/log/odoo/odoo-server.log   # or docker logs odoo

# Static XML sanity check (no container needed)
python3 -c "import xml.dom.minidom as m; m.parse('path/to/file.xml')"
```

Use a scratch database (e.g. `test_infohub`) for tests, not the main `odoo` db. Python deps beyond the image are pip-installed manually into the container and are lost on container recreation (e.g. `feedparser`).

## Quality gates — required before declaring work done

1. **Addon loads cleanly**: `docker exec odoo odoo -c /etc/odoo/odoo.conf -d <test_db> -u <addon> --stop-after-init --workers=0 --no-http` exits 0 (catches manifest errors, broken XML/views, import errors).
2. **Unit tests pass**: run the touched addon's tests with `--test-tags /<addon>` (command above). If you changed shared code in a core addon (`llm`, `llm_knowledge`, `llm_store`, `component`, …), run the tests of the dependent addons too.
3. **XML is well-formed**: `python3 -c "import xml.dom.minidom as m; m.parse('<file>')"` for every view/security/data XML you touched (cheap, no container needed).
4. **No real network calls in tests**: mock provider adapters/endpoints. Unit tests must pass on a machine with no API keys configured.
5. For `infohub*/` changes: additionally run the shell test scripts listed in `.kiro/specs/infohub/progress.md` and `python3 .kiro/specs/infohub/check_refs.py`.

## Testing conventions

- Tests live in `<addon>/tests/` and must be imported in `tests/__init__.py` (Odoo only discovers modules listed there).
- Standard shape (see `llm/tests/`): `@tagged("post_install", "-at_install")` on the class, `odoo.tests.common.TransactionCase` as base. Use `HttpCase` only for endpoints/UI.
- Component behavior is tested with `TransactionComponentRegistryCase` from `odoo.addons.component.tests.common` (see `llm/tests/test_provider_dispatch.py`).
- Core addons ship no provider implementations — tests inject fake services by extending Selection fields (`selection_value` helper in `llm/tests/common.py`) and `mock.patch.object` on adapter methods. Follow this pattern instead of adding test-only providers.
- New external Python deps must be declared in `__manifest__.py` `external_dependencies` and pip-installed in the container before tests will pass.

## Addon families and architecture

Three in-house stacks plus vendored OCA addons:

**LLM stack** — the largest active area:
- `llm` — core: provider/model abstraction (dispatch via `llm_provider_adapter` component), chat threads, assistants, tool framework incl. the `@llm_tool` decorator (`llm/decorators.py`, see `llm/DECORATOR.md`) and built-in CRUD tools, MCP client. Formerly split into `llm_thread`/`llm_tool`/`llm_assistant` — merged into `llm`.
- Providers: `llm_openai` (→ `llm_openai_compatible`), `llm_anthropic`.
- `llm_store` — vector store abstraction (`llm.store` model + `llm.store.adapter` component contract), splitters (`recursive`/`token`/`contextual` — contextual retrieval is a splitter variant, not a chunkset field), chunksets/vectors. Chunk **text lives in the vector store payload**, not in Odoo DB columns.
- Vector adapters: `llm_pgvector` (external Postgres), `llm_qdrant`, `llm_knowledge_pgvector` (embeddings inside Odoo's own DB via `base_pgvector` field type).
- `llm_knowledge` — knowledge collections + resource lifecycle (`draft→retrieved→parsed→chunked→ready`) and the extractor API. Deliberately dependency-light: extraction libs live in optional satellite addons (`llm_knowledge_extractor_{markitdown,trafilatura,mineru}`, `llm_knowledge_parser_{markdownify,pymupdf}`, `llm_knowledge_retriever_http`). New extractor addons follow the extension API in `llm_knowledge/README.md` (component with unique `_usage`, `_input`, `_output_format`; `selection_add` on `extractor_type` with ondelete policy; declare only own pip deps; never auto_install).
- `llm_mcp_server` — exposes Odoo tools to external AI clients via MCP. `llm_discuss`/`llm_discuss_livechat` — chat UI.
- Design context for the knowledge/store merge: `.kiro/specs/knowledge-merge/design.md` (chunk text in vector payload, multi-chunkset/vector model, `md_backend_id` per collection).

**InfoHub stack** — online info aggregation (RSS/blogs/papers/social):
- `infohub` core + satellites (`infohub_rss`, `infohub_arxiv`, `infohub_web`, `infohub_website`, `infohub_fulltext`, `infohub_paper`, `infohub_filter`, `infohub_digest`, `infohub_llm`).
- Three-axis model: `infohub.source = medium × transport × provider`, orthogonal axes, no cross-axis inheritance, no `if source.provider == ...` branches in callers — add a component instead. Full constraints in `.kiro/steering/infohub.md` (read before touching `infohub*/`), rejected-alternatives in `.kiro/specs/infohub/decisions.md` (read before changing design).
- Shell-based test scripts live in `.kiro/specs/infohub/*_test.py`; run them per the commands in `.kiro/specs/infohub/progress.md`.

**Storage/cloud stack**:
- `storage_backend` (OCA) + `storage_backend_{s3,sftp,ftp}` adapters; `one_storage` — VFS layer over storage backends (see `one_storage/README.rst`); `one_cloud*` — cloud account/firewall integrations.

**Vendored OCA addons** (avoid gratuitous changes): `component`, `component_event`, `connector`, `queue_job*`, `server_environment`, `spreadsheet_oca`, `spreadsheet_dashboard_oca`, `web_*`, `base_pgvector` (in-house but foundational).

### Cross-cutting patterns

- **Multi-provider integrations use the component framework with layered addons**: a core addon defines abstract components + a polymorphic host model; each provider gets its own small addon registering a component (unique `_usage`) and extending the host's Selection field via `selection_add`. Do not grow a single big addon with provider `if/else` branches. Examples: `llm_knowledge` + extractor addons; `llm_store` + vector adapters; `infohub` three-axis.
- **queue_job** for anything slow (fetch, sync, batch): `record.with_delay(channel="root.<family>", description=..., identity_key="<unique-per-record>")` with channel capacity set in `odoo.conf` `[queue_job] channels` — missing channel config fails silently (e.g. `root.infohub.arxiv:1` exists for rate limiting).
- **SSRF**: server-side outbound HTTP to user-supplied URLs must go through the shared HTTP component base class (scheme allowlist, private-range/loopback/link-local blocking, per-hop redirect rechecks, timeouts + response size caps). No direct `requests.get`.
- Rendering third-party HTML on public pages: `fields.Html(sanitize=True)` and `t-out` only, never `t-raw`.

## Odoo 19 conventions (differ from older Odoo)

- Version `19.0.x.y.z`, license `LGPL-3`, author `quick-sort@outlook.com` for in-house addons.
- SQL constraints: `models.Constraint` (`_sql_constraints` unsupported); composite indexes via `models.Index`.
- Domain building: `from odoo.fields import Domain` (`odoo.osv.expression` deprecated).
- List views use `<list>` not `<tree>`; dynamic attributes written directly (`invisible="..."`), no `attrs=`.
- Aggregates: `aggregator=`, not `group_operator=`.
- Delete guards: `@api.ondelete(at_uninstall=False)`, don't override `unlink`.
- Python deps go in `__manifest__.py` `external_dependencies`; Odoo checks but does not install them.
- Directory layout: `models/ components/ views/ security/ data/ wizards/ tests/`.

### Component framework gotchas (applies to every stack)

- Component inheritance must use `_inherit = "parent.component.name"` — Python class inheritance is ignored by the registry.
- Never define methods named `_abstract`, `_name`, `_inherit`, `_collection`, `_usage`, `_apply_on`, `_register`, `_module` in a component class — they are framework-reserved class attributes. Defining `_abstract` as a method flips it truthy and silently excludes the component from lookup (`NoComponentError`).
- `WorkContext.component()` raises `SeveralComponentError` when multiple components match; disambiguation is only by collection and model, so lookup keys (e.g. `_usage` per provider type) must be unique within a collection.

## Reference docs in-repo

- `.claude/skills/odoo-19/references/` — 18 Odoo 19 guides (views, decorators, testing, security, …). Consult these when writing Odoo XML/Python.
- `llm/DECORATOR.md` — `@llm_tool` decorator guide; `llm/OPENAI_SCHEMA_COMPATIBILITY.md` — schema notes.
- Per-addon `README.md`/`README.rst` — install matrices and extension APIs, especially `llm_knowledge/README.md`.
- `.kiro/specs/*/` — design docs, requirements, and ADR-style decisions; `.kiro/steering/infohub.md` — infohub constraints (auto-scoped to `infohub*/`).
