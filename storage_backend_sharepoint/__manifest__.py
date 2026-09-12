{
    "name": "Storage Backend SharePoint",
    "summary": "Access SharePoint document libraries with each user's Entra permissions",
    "version": "19.0.1.0.0",
    "category": "Storage",
    "author": "quick-sort@outlook.com",
    "website": "https://github.com/OCA/storage",
    "license": "LGPL-3",
    "installable": True,
    "external_dependencies": {"python": ["requests"]},
    "depends": ["storage_backend"],
    "data": [
        "security/ir.model.access.csv",
        "views/backend_storage_view.xml",
    ],
}
