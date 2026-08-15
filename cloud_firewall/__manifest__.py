# Copyright 2026 Rui
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

{
    "name": "云防火墙白名单同步",
    "summary": "定时检查公网 IP 变化，通过云服务商组件自动同步防火墙白名单",
    "version": "19.0.1.0.0",
    "category": "Technical",
    "author": "Rui",
    "license": "LGPL-3",
    "installable": True,
    "application": True,
    "depends": ["cloud"],
    "data": [
        "security/ir.model.access.csv",
        "data/cloud_firewall_data.xml",
        "views/cloud_account_views.xml",
        "views/cloud_firewall_target_views.xml",
        "views/cloud_firewall_sync_config_views.xml",
        "views/cloud_firewall_sync_log_views.xml",
        "views/cloud_firewall_menus.xml",
    ],
}
