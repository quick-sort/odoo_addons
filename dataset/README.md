# Dataset Management

Odoo 19 catalog for dataset sources, package hierarchies, manifests, datasets,
and addressable data chunks. It depends on `web_json_editor`; CSV/Parquet table
preview also requires the manifest-declared `pyarrow` package.

Chunk keys are `source/dataset.<type>` or
`source/dataset/<metadata values>.<type>`. Every component is validated:
empty values, missing key-field metadata, `.`, `..`, slash, and backslash are
rejected. `dataset.data_chunk.raw_data` is attachment-backed when this addon is
installed alone. The optional `dataset_storage` addon redirects payload I/O to
an OCA `storage.backend`.

Dataset Manager users have CRUD access. Chunk-to-dataset deletion uses
`ondelete='restrict'`. Manifests declare expected metadata values and datasets
compute expected count and fill rate after their optional filter domain.

License: LGPL-3.
