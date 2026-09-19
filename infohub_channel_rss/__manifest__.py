{
    "name": "InfoHub RSS Channel",
    "summary": "Poll RSS and Atom feeds into the InfoHub pool",
    "version": "19.0.1.0.0",
    "author": "quick-sort@outlook.com",
    "website": "quick-sort@outlook.com",
    "license": "LGPL-3",
    "category": "Productivity",
    "depends": ["infohub"],
    "external_dependencies": {"python": ["requests"]},
    "data": [
        "data/queue_data.xml",
        "views/infohub_channel_views.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
