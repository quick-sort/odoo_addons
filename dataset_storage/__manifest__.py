{
    "name": "Dataset Storage",
    "version": "19.0.1.0.0",
    "category": "Tools",
    "summary": "Store dataset chunks through OCA storage backends",
    "author": "Quick Sort",
    "website": "",
    "license": "LGPL-3",
    "depends": ["dataset", "storage_backend", "queue_job"],
    "data": [
        "data/storage_data.xml",
        "views/dataset_views.xml",
        "views/data_chunk_views.xml",
    ],
    "installable": True,
    "application": False,
}
