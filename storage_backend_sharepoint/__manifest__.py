{
    "name": "Storage Backend SharePoint",
    "summary": "Access SharePoint document libraries with each user's Entra permissions",
    "version": "19.0.2.0.0",
    "category": "Storage",
    "author": "quick-sort@outlook.com",
    "website": "https://github.com/OCA/storage",
    "license": "LGPL-3",
    "installable": True,
    "external_dependencies": {"python": ["requests"]},
    "depends": ["storage_backend", "microsoft_graph"],
    "data": [
        "views/backend_storage_view.xml",
    ],
}
