{
    "name": "InfoHub 前端阅读",
    "summary": "portal 读者在网站端浏览个人信息流、管理订阅",
    "description": """
InfoHub 前端阅读
================
给 portal 读者提供网站端的阅读界面：个人信息流、条目详情、订阅管理。
后台的 Odoo 标准视图保留给内部用户做源管理与审核。

路由
----
=================================  ========  ============================
路由                               auth      说明
=================================  ========  ============================
``/infohub``                       user      个人信息流（筛选 + 分页）
``/infohub/item/<id>``             user      条目详情，打开即记为已读
``/infohub/subscriptions``         user      订阅与偏好管理
``/infohub/topic/<topic>``         public    公开学科浏览页
=================================  ========  ============================

另有若干 ``type='jsonrpc'`` 端点用于收藏/隐藏/已读的即时切换。

个性化与安全边界的分工
----------------------
条目的记录规则只按 ``state`` 与 ``access_level`` 两个索引字段过滤，**不按订阅
过滤**（ADR-015）——按 m2m 订阅做记录规则需要联表，在几十万行上会退化成慢查询。
订阅是**展示逻辑**，在控制器里用 ``res.users._infohub_timeline_domain()`` 完成。

这个取舍的前提是"内容都是公开网页信息"，读到未订阅的条目不构成机密泄露。
真正需要隔离的是订阅与阅读状态，它们有 ``user_id = user.id`` 记录规则。

自助注册
--------
依赖 ``auth_signup``。新注册用户自动加入 ``infohub.group_reader``，并按标记为
「推荐订阅」的学科与信息源建立默认订阅，避免首屏信息流为空。
    """,
    "author": "quick-sort@outlook.com",
    "website": "quick-sort@outlook.com",
    "category": "Website/Portal",
    "version": "19.0.1.0.0",
    "depends": [
        "infohub",
        "website",
        "portal",
        "auth_signup",
    ],
    "data": [
        "security/ir.model.access.csv",
        "views/infohub_portal_templates.xml",
        "views/infohub_timeline_templates.xml",
        "views/infohub_item_templates.xml",
        "views/infohub_subscription_templates.xml",
        "views/infohub_topic_templates.xml",
        "views/website_menu.xml",
    ],
    "assets": {
        "web.assets_frontend": [
            "infohub_website/static/src/scss/infohub_portal.scss",
            "infohub_website/static/src/js/infohub_reader.js",
        ],
    },
    "license": "LGPL-3",
    "installable": True,
    "application": False,
    "auto_install": False,
}
