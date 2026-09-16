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

### Throwaway containers must not touch production ports

A production deployment lives in `../devop/deploy/docker-compose.yml` and owns these host ports — never publish them from a scratch container:

| Port | Used by |
|---|---|
| `8069` | Odoo HTTP workers (nginx reverse-proxied) |
| `8072` | Odoo gevent worker (websocket) |
| `24224` | fluent-bit log shipping (tcp + udp) |
| `5432` | Postgres — deliberately **not** published; the odoo container reaches it over the docker network |
| `3000` | an unrelated long-running agent container on this host |

Note that `odoo:19.0` **EXPOSE**s 8069/8071/8072 in its image config. Exposed is not published: it costs nothing until a `-p` is passed. Omitting `-p` entirely is the safest habit, and it is what the scratch containers use — they reach each other by container name over the existing external `main` network (reuse it, do not create a new one).

For one-shot commands add `--workers=0 --no-http --http-port=0`; without `--http-port=0` Odoo still tries to bind 8069 even under `--no-http` when `queue_job` is a server-wide module. If a scratch container genuinely needs to serve HTTP, map a high port explicitly, e.g. `-p 127.0.0.1:8099:8069`.

## Quality gates — required before declaring work done

1. **Addon loads cleanly**: `docker exec odoo odoo -c /etc/odoo/odoo.conf -d <test_db> -u <addon> --stop-after-init --workers=0 --no-http` exits 0 (catches manifest errors, broken XML/views, import errors).
2. **Unit tests pass**: run the touched addon's tests with `--test-tags /<addon>` (command above). If you changed shared code in a core addon (`llm`, `llm_knowledge`, `llm_store`, `component`, …), run the tests of the dependent addons too.
3. **XML is well-formed**: `python3 -c "import xml.dom.minidom as m; m.parse('<file>')"` for every view/security/data XML you touched (cheap, no container needed).
4. **No real network calls in tests**: mock provider adapters/endpoints. Unit tests must pass on a machine with no API keys configured.

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
- `llm_knowledge` — knowledge collections + native `llm.document` lifecycle (`draft→retrieved→processed`, then downstream `chunked`/`ready` states), built-in safe HTTP/HTTPS binary retrieval, and the extractor API. Extraction libraries remain in optional satellite addons (`llm_knowledge_extractor_{markitdown,trafilatura,mineru}`). New extractor addons follow the extension API in `llm_knowledge/README.md` (component with unique `_usage`; `selection_add` on `extractor_type` with ondelete policy; declare only own pip deps; never auto_install).
- `llm_mcp_server` — exposes Odoo tools to external AI clients via MCP. `llm_discuss`/`llm_discuss_livechat` — chat UI.

**InfoHub stack** — news aggregation into one pool:
- `infohub` core + channel addons (`infohub_channel_rss`, `infohub_channel_email`, `infohub_channel_mcp`).
- **Two orthogonal dimensions, not one.** A *source* is whose the news is (a publisher: `name` + `url`); a *channel* is how it is obtained (RSS / inbound email / a third-party API). The same publisher may be reachable through several channels, so an item carries both: `source_id` says who it belongs to, `channel_id` says how it arrived.
- Channels are `component` collections. A channel addon contributes a `selection_add` value on `channel_type`, its own config fields via `_inherit` (the core keeps no channel-specific columns), and `infohub.fetch.<type>` / `infohub.content.<type>` components. Components resolve by **usage suffix** (`usage=f"infohub.fetch.{channel_type}"`) rather than `_component_match` disambiguation, so usages stay unique by construction.
- **The core never depends on `llm`.** Only `infohub_channel_mcp` does. A test asserts the core's dependency list, and the split is verified by installing core + rss + email in a database with no `llm`.
- Inbound email routes through the `infohub.email.message` relay (it inherits `mail.thread`), never through `infohub.item` — that keeps chatter tables from growing with the number of pooled items.
- Failure bookkeeping (`error_count` / `last_error`) is written on a **separate cursor**, because a queue_job failure rolls the caller's transaction back and would otherwise discard it. Odoo's test `assertRaises` rolls back the same way.
- The previous three-axis design (`medium × transport × provider`) is retired; its 10 modules are kept under `legacy/` for reference and are not loaded by Odoo (`legacy/` has no root `__manifest__.py`, and the addons scan is a non-recursive `os.listdir`).

**Storage/cloud stack**:
- `storage_backend` (OCA) + `storage_backend_{s3,sftp,ftp}` adapters; `one_storage` — VFS layer over storage backends (see `one_storage/README.rst`); `one_cloud*` — cloud account/firewall integrations.

**Vendored OCA addons** (avoid gratuitous changes): `component`, `component_event`, `connector`, `queue_job*`, `server_environment`, `spreadsheet_oca`, `spreadsheet_dashboard_oca`, `web_*`, `base_pgvector` (in-house but foundational).

### Cross-cutting patterns

- **Multi-provider integrations use the component framework with layered addons**: a core addon defines abstract components + a polymorphic host model; each provider gets its own small addon registering a component (unique `_usage`) and extending the host's Selection field via `selection_add`. Do not grow a single big addon with provider `if/else` branches. Examples: `llm_knowledge` + extractor addons; `llm_store` + vector adapters; `infohub_channel_*`.
- **queue_job** for anything slow (fetch, sync, batch): `record.with_delay(channel="root.<family>", description=..., identity_key="<unique-per-record>")` with channel capacity set in `odoo.conf` `[queue_job] channels` — missing channel config fails silently (e.g. `root.infohub` is declared for channel fetches but no capacity is configured in `devop/deploy/odoo/odoo.conf`).
- **SSRF**: server-side outbound HTTP to user-supplied URLs must be validated — scheme allowlist, private-range/loopback/link-local blocking, per-hop redirect rechecks (follow redirects manually with `allow_redirects=False`), timeouts + response size caps. `infohub/url_guard.py` is the in-house helper; `llm_knowledge/models/llm_document_http.py` is a stricter variant that additionally pins the validated IP. No unguarded `requests.get`.
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
