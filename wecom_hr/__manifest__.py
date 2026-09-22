{
    "name": "WeCom HR 同步",
    "version": "19.0.1.0.0",
    "category": "WeCom",
    "summary": "从企业微信同步部门与成员到 Odoo HR",
    "author": "quick-sort@outlook.com",
    "website": "quick-sort@outlook.com",
    "license": "LGPL-3",
    "depends": ["wecom", "hr"],
    "data": [
        "views/wecom_app_views.xml",
        "data/ir_cron_data.xml",
    ],
    "installable": True,
    "application": False,
    "auto_install": False,
}
