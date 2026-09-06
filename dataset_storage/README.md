# Dataset Storage

Odoo 19 integration between the `dataset` catalog and the existing OCA
`storage.backend` API. It contains no provider implementation. Configure
filesystem, S3, or another installed storage provider on a `storage.backend`
record, then assign it to a dataset before creating chunks. The backend cannot
be changed after chunks exist because their payload keys belong to that
backend.

A credential-free default filesystem backend is installed with the relative
`directory_path` `datasets` and transparent gzip for CSV, JSON, and JSONL.
Provider credentials belong on provider-specific `storage.backend` fields or
server-environment configuration, never in this addon. Backend configuration
remains restricted to System users; dataset payload methods first enforce
chunk ACLs and record rules, then mediate only the selected backend operation
with service privileges.

Chunk binary reads and writes use `storage.backend.open`; existence, physical
stored size, and explicit cleanup use `file_exists`, `get_size`, and `delete`.
The Binary field remains base64 at the Odoo boundary. Dataset size is the sum
of physical chunk sizes expressed in GiB. Reading the computed payload does not
change persistent size or state. Catalog rows with an existing payload are
protected from unlink: use **Delete Stored Payload** first, then delete the row.

**Reconcile Storage** queues one scan using `queue_job`. The worker holds a
per-dataset PostgreSQL transaction advisory lock through listing and every
reconciliation batch; storage/key configuration writes join the same lock, so
overlapping scans and reconfiguration cannot race. Dataset payload paths are
explicitly marked logical at the adapter boundary, preserving valid first path
components that happen to equal the configured backend root while retaining
legacy rooted-path compatibility for other storage callers. Keyed datasets use
one recursive detailed listing; single-file datasets use exact existence and
size calls. Every batch revalidates storage before it creates, refreshes,
restores, or marks a chunk missing.

License: LGPL-3.
