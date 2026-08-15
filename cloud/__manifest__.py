# Copyright 2026 Rui
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

{
    "name": "云平台",
    "summary": "云账号与凭证管理基座，配合 component 多态扩展各云服务商",
    "version": "19.0.1.0.0",
    "category": "Technical",
    "author": "Rui",
    "license": "LGPL-3",
    "installable": True,
    "application": True,
    "depends": ["base", "component"],
    "data": [
        "security/cloud_security.xml",
        "security/ir.model.access.csv",
        "views/cloud_account_views.xml",
        "views/cloud_menus.xml",
    ],
}
