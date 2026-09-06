{
    "name": "Dataset Management",
    "version": "19.0.1.0.0",
    "category": "Tools",
    "summary": "Catalog and manage datasets for AI training and evaluation",
    "description": """
Dataset Management
==================
Catalog, organize, preview, and track datasets used for AI/ML training and evaluation.
Storage backends are provided by the optional dataset_storage integration addon.
    """,
    "author": "Quick Sort",
    "website": "",
    "license": "LGPL-3",
    "icon": "/dataset/static/description/icon.svg",
    "depends": ["base", "web_json_editor"],
    "external_dependencies": {"python": ["pyarrow"]},
    "data": [
        "security/dataset_manager.xml",
        "security/ir.model.access.csv",
        "views/source_views.xml",
        "views/package_views.xml",
        "views/manifest_views.xml",
        "views/data_chunk_views.xml",
        "views/dataset_views.xml",
        "views/tag_views.xml",
        "views/menu.xml",
        "wizard/table_preview_wizard_views.xml",
    ],
    "demo": ["demo/dataset_demo.xml"],
    "images": ["static/description/icon.svg"],
    "installable": True,
    "application": True,
}
