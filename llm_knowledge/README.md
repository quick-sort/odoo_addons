# LLM Knowledge

Dependency-light knowledge collection and resource management for Odoo RAG workflows.
`llm_knowledge` owns the resource lifecycle, extractor configuration model, and the
abstract component contract. Document extraction libraries live in optional addons,
so a core installation does not require every supported parser.

## Architecture

```text
llm_knowledge                         core resource lifecycle and extractor API
├── llm_knowledge_extractor_markitdown   local files → Markdown
├── llm_knowledge_extractor_trafilatura  web URLs → Markdown
├── llm_knowledge_extractor_mineru       files → MinerU JSON
├── llm_knowledge_parser_markdownify     legacy HTML fields → Markdown
├── llm_knowledge_parser_pymupdf         legacy PDF fields → Markdown + images
└── llm_knowledge_retriever_http          legacy attachment URLs → content
```

The optional addons are not auto-installed. Install only the implementations needed
by a database.

## Installation

Core has no third-party Python extraction dependency:

```bash
odoo-bin -d your_database -i llm_knowledge
```

Choose optional features independently:

| Feature | Odoo addon | Python import/package |
| --- | --- | --- |
| Local Office/PDF/HTML extraction | `llm_knowledge_extractor_markitdown` | `markitdown` |
| Web article extraction | `llm_knowledge_extractor_trafilatura` | `trafilatura` |
| External MinerU service | `llm_knowledge_extractor_mineru` | `requests` |
| Legacy HTML field parsing | `llm_knowledge_parser_markdownify` | `markdownify` |
| Legacy PDF field parsing | `llm_knowledge_parser_pymupdf` | `pymupdf` (`PyMuPDF`) |
| Legacy attachment URL retrieval | `llm_knowledge_retriever_http` | `requests`, `markdownify` |

For example, a deployment that extracts only web pages needs only Trafilatura:

```bash
python3 -m pip install trafilatura
odoo-bin -d your_database -i llm_knowledge_extractor_trafilatura
```

A deployment that sends files to MinerU needs only Requests locally:

```bash
python3 -m pip install requests
odoo-bin -d your_database -i llm_knowledge_extractor_mineru
```

Odoo checks each addon's `external_dependencies`; it does not install Python packages.
Pin package versions in the deployment's own requirements or lock file.

## Configure an extractor

Installing an extractor addon registers its component and adds its technical type to
`llm.resource.extractor`. Create at least one active extractor record before processing
file or URL resources.

```python
extractor = env["llm.resource.extractor"].create(
    {
        "name": "Web pages",
        "extractor_type": "trafilatura",
    }
)

resource = env["llm.resource"].create(
    {
        "name": "Odoo documentation",
        "source_type": "url",
        "source_url": "https://www.odoo.com/documentation/19.0/",
        "extractor_id": extractor.id,
        "collection_ids": [(4, collection.id)],
    }
)
resource.process_resource()
```

Without an explicit `extractor_id`, the first active installed extractor compatible
with the resource source type is used. Extractor records whose implementation addon is
not installed are skipped. An explicit unavailable or incompatible extractor produces
a clear resource error instead of aborting fallback discovery.

MinerU's API URL and API key fields are provided by
`llm_knowledge_extractor_mineru` and appear only when that addon is installed.

## Core behavior without optional addons

Core can still parse plain text, Markdown, JSON, and image references from record-backed
resources. Unsupported binary, PDF, or HTML fields produce a link and a message that an
optional parser is required. File and URL resources require one of the extractor addons.

The upload wizard now creates files and external URLs as native `source_type="file"`
and `source_type="url"` resources. Uploaded bytes are copied into `one.storage`, so the
wizard uses the selected file/URL extractor path and no longer forces legacy parser or
HTTP dependencies.

## Upgrading an existing database

The technical extractor values remain unchanged: `markitdown`, `trafilatura`, and
`mineru`. After deploying this code, install every optional addon used by existing
records in the same maintenance operation:

```bash
odoo-bin -d your_database \
  -u llm_knowledge \
  -i llm_knowledge_extractor_markitdown,llm_knowledge_extractor_trafilatura
```

Also install:

- `llm_knowledge_extractor_mineru` when a MinerU extractor record exists;
- `llm_knowledge_retriever_http` while legacy resources use `retriever="http"`;
- `llm_knowledge_parser_pymupdf` to preserve legacy attachment PDF parsing;
- `llm_knowledge_parser_markdownify` to preserve legacy attachment HTML parsing.

Existing columns and technical values are preserved. Once legacy HTTP resources have
been migrated to native URL resources, the compatibility retriever addon can be removed.

## Extension API

A new extractor addon should:

1. depend on `llm_knowledge`;
2. register a component inheriting `llm.resource.extractor.component` with a unique
   `_usage`, `_input` (`file` or `url`), and `_output_format` (`md` or `json`);
3. extend `extractor_type` with `fields.Selection(selection_add=[...])` and an
   `ondelete` policy such as `archive_dangling_extractor`;
4. declare only its own Python packages in `external_dependencies`;
5. remain non-auto-installable so administrators choose the dependency footprint.

Chunking, embedding, and vector search are supplied by downstream addons such as
`llm_store` and `llm_knowledge_pgvector`.
