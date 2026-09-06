{
    "name": "Dataset DataFrame",
    "version": "19.0.1.0.0",
    "category": "Tools",
    "summary": "Read dataset chunks as Polars DataFrames",
    "description": """
Dataset DataFrame
=================
Read CSV and Parquet dataset chunks as Polars DataFrames.
    """,
    "author": "Quick Sort",
    "website": "",
    "license": "LGPL-3",
    "depends": ["dataset"],
    "external_dependencies": {"python": ["polars"]},
    "data": ["views/data_chunk_views.xml"],
    "installable": True,
    "application": False,
}
