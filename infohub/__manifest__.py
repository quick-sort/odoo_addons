{
    "name": "InfoHub",
    "summary": "在线信息聚合：RSS 新闻、博客、论文、社交内容的统一收集与订阅",
    "description": """
InfoHub
=======
把分散在 RSS 新闻、博客、学术论文、社交平台上的在线信息汇集成统一的、
可按学科/标签订阅的信息流。

本模块是核心层，提供：

* ``infohub.source`` —— 信息源，是 component 的 collection
* ``infohub.item`` —— 归一化条目
* ``infohub.topic`` / ``infohub.tag`` —— 学科受控词表与自由标签
* ``infohub.subscription`` —— 每用户订阅
* ``infohub.item.read`` —— 每用户阅读状态
* 审核状态机与人工标黑
* HTTP 客户端组件基类（含 SSRF 防护）
* 三轴 component 抽象基类

三轴组合模型
------------
信息源由三个正交维度组合定义::

    infohub.source = medium × transport × provider
                       介质      传输       来源

* ``medium`` 决定条目的字段语义与去重身份算法
* ``transport`` 决定怎么拿到字节、怎么做增量
* ``provider`` 决定该来源特有的字段映射

三个维度各自由卫星模块用 ``_selection_add`` 扩展，互不继承。核心不含任何
来源判断分支。

设计文档见 ``.kiro/specs/infohub/``。
    """,
    "author": "quick-sort@outlook.com",
    "website": "quick-sort@outlook.com",
    "category": "Productivity",
    "version": "19.0.1.0.0",
    "depends": [
        "base",
        "mail",
        "component",
        "queue_job",
    ],
    "data": [
        "security/infohub_groups.xml",
        "security/ir.model.access.csv",
        "security/infohub_security.xml",
        "data/queue_data.xml",
        "data/infohub_topic_data.xml",
        "data/ir_cron_data.xml",
        "views/infohub_topic_views.xml",
        "views/infohub_tag_views.xml",
        "views/infohub_credential_views.xml",
        "views/infohub_source_views.xml",
        "views/infohub_source_preset_views.xml",
        "views/infohub_source_run_views.xml",
        "views/infohub_item_views.xml",
        "views/infohub_blocklist_views.xml",
        "views/infohub_subscription_views.xml",
        "views/infohub_menus.xml",
    ],
    "license": "LGPL-3",
    "installable": True,
    "application": True,
    "auto_install": False,
}
