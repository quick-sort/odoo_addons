# Copyright 2026 One Storage
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

{
    "name": "One Storage",
    "summary": "Unified file storage with mountable VFS and async batch ops",
    "version": "19.0.1.3.0",
    "category": "Storage",
    "author": "One Storage, Odoo Community Association (OCA)",
    "website": "https://github.com/OCA/storage",
    "license": "LGPL-3",
    "development_status": "Beta",
    "depends": ["base", "queue_job", "storage_backend"],
    "external_dependencies": {},
    "data": [
        "security/one_storage_security.xml",
        "data/queue_data.xml",
        "views/one_storage_entry_views.xml",
        "views/storage_backend_views.xml",
        "views/one_storage_operation_views.xml",
        "views/one_storage_menus.xml",
        "wizards/one_storage_entry_create_wizard_views.xml",
        "wizards/one_storage_entry_delete_wizard_views.xml",
        "wizards/one_storage_entry_mount_wizard_views.xml",
        "wizards/one_storage_entry_move_wizard_views.xml",
        "wizards/one_storage_entry_rename_wizard_views.xml",
        "wizards/one_storage_entry_upload_wizard_views.xml",
        "security/ir.model.access.csv",
    ],
    "assets": {
        "web.assets_backend": [
            "one_storage/static/src/kanban/*.js",
        ],
    },
    "installable": True,
    "application": True,
    "post_init_hook": "post_init_hook",
}
