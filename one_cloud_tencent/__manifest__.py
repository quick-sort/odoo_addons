# Copyright 2026 Rui
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

{
    "name": "云防火墙 - 腾讯云轻量应用服务器",
    "summary": "腾讯云 Lighthouse 防火墙白名单同步适配器",
    "version": "19.0.1.0.0",
    "category": "Technical",
    "author": "Rui",
    "license": "LGPL-3",
    "installable": True,
    "application": False,
    "external_dependencies": {"python": ["tencentcloud-sdk-python-lighthouse"]},
    "depends": ["one_cloud_firewall"],
    "data": [
        "views/one_cloud_account_views.xml",
        "views/one_cloud_firewall_target_views.xml",
    ],
}
