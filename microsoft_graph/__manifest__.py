{
    "name": "Microsoft Graph",
    "summary": "Entra ID delegated OAuth and Microsoft Graph client for user-bound integrations",
    "version": "19.0.1.0.0",
    "category": "Tools",
    "author": "quick-sort@outlook.com",
    "website": "",
    "license": "LGPL-3",
    "depends": ["server_environment"],
    "external_dependencies": {"python": ["requests"]},
    "data": [
        "security/ir.model.access.csv",
        "views/microsoft_graph_application_views.xml",
        "views/microsoft_graph_menus.xml",
    ],
    "application": False,
    "auto_install": False,
    "installable": True,
}
