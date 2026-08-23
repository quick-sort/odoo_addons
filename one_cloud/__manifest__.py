# Copyright 2026 Rui
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

{
    "name": "One Cloud",
    "summary": "云账号与凭证管理基座，配合 component 多态扩展各云服务商",
    "version": "19.0.1.0.0",
    "category": "Technical",
    "author": "quick-sort",
    "license": "LGPL-3",
    "installable": True,
    "application": True,
    "images": ["static/description/icon.png"],
    "depends": ["base", "component"],
    "data": [
        "security/one_cloud_security.xml",
        "security/ir.model.access.csv",
        "views/one_cloud_account_views.xml",
        "views/one_cloud_menus.xml",
    ],
}
