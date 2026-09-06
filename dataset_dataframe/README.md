# Dataset DataFrame

Odoo 19 integration that reads CSV and Parquet `dataset.data_chunk` payloads as
Polars DataFrames. Unsupported, missing, and empty payloads return no frame;
malformed supported payloads raise the parser error. Configured key-field
metadata is added only when present on the chunk and absent from payload columns.

Payload access remains storage-transparent through the dataset chunk payload API,
so attachment-backed and optional external storage use the same conversion path.
Dataset conversion processes chunks deterministically by ascending record ID and
combines available frames with relaxed vertical schema coercion.

Conversions load each payload and the combined result into memory. Schema
coercion may widen types, and the explicitly refreshed record count is only a
snapshot of the last successful refresh.

License: LGPL-3.
