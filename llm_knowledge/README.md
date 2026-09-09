# LLM Knowledge

`llm_knowledge` provides native file and URL documents for Odoo RAG workflows.
Each `llm.document` belongs to exactly one collection and follows a binary retrieval
→ Markdown extraction lifecycle. HTTP retrieval is built into the core addon; optional
addons provide extraction, while `llm_store` and vector backends provide chunking,
embedding, and vector search.

## Architecture

```text
llm.knowledge.collection
└── document_ids → llm.document
    ├── file: source_backend_id + source_path
    ├── URL: source_url + collection cache backend
    ├── retrieve() → binary envelope
    ├── extract() → Markdown
    └── process_document() → retrieve + extract (+ downstream split/embed)
```

Core extractor configuration uses:

- `llm.document.extractor` — polymorphic extractor host;
- `llm.document.extractor.mapping` — collection-specific or global MIME/extension routing;
- `llm.document.extractor.component` — component contract returning Markdown `str`.

Cache artifacts use `collections/<collection_id>/documents/<document_id>/`. No legacy
model alias or cache-path fallback is provided.

## Installation

Install the `requests` Python package, then install the addon:

```bash
python3 -m pip install requests
odoo-bin -d your_database -i llm_knowledge
```

Core has no third-party extraction dependency. Install only the optional extractor
implementations required by the deployment:

| Capability | Addon | Python dependency |
| --- | --- | --- |
| Local file extraction | `llm_knowledge_extractor_markitdown` | `markitdown` |
| Web article extraction | `llm_knowledge_extractor_trafilatura` | `trafilatura` |
| External MinerU extraction | `llm_knowledge_extractor_mineru` | `requests` |

The deprecated parser addons are intentionally disabled and are not part of the native
document pipeline.

## HTTP URL retrieval

Native URL retrieval accepts absolute HTTP and HTTPS URLs, follows at most five redirects,
uses 10-second connect and 60-second read timeouts, and limits responses to 50 MiB. Every
redirect and the connected peer are checked against private, loopback, link-local,
reserved, multicast, and unspecified addresses to reduce SSRF risk. Proxy environment
variables are intentionally ignored.

Private destinations are blocked by default. Trusted deployments can explicitly set the
system parameter `llm_knowledge.allow_private_urls` to `True`; this is a global security
relaxation and should not be enabled for untrusted users. Force refresh uses stored ETag
and Last-Modified values for conditional requests, while normal processing reuses the
cached binary.

## Configure extraction

Create an extractor and route supported files or URLs to it with a mapping:

```python
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
```

A document-level `extractor_id` is the highest-priority override. Otherwise collection
mappings are evaluated before global mappings, using exact MIME, exact extension, MIME
wildcard, then blank-default priority.

## Upload and storage scan

The upload wizard creates native file/URL documents. Uploaded files are copied to the
collection's Source Backend. URL documents require a cache backend. Collections can
scan their source backend recursively: new files create documents, missing files are
flagged `to_delete`, and reappearing files clear that flag.

## Extension contract

An extractor addon should:

1. depend on `llm_knowledge`;
2. register a component inheriting `llm.document.extractor.component` with a unique
   `_usage` and an `extract(envelope) -> Markdown str` implementation;
3. extend `llm.document.extractor.extractor_type` with `selection_add` and an
   `ondelete` policy such as `archive_dangling_extractor`;
4. declare only its own external Python dependencies;
5. document the MIME/extension mappings required to select it.

This development branch intentionally provides no database migration, old model alias,
old cache fallback, or old vector payload compatibility. Reindex vector collections
after deployment.
