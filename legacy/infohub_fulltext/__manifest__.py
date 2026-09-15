{
    "name": "InfoHub 正文提取",
    "summary": "为只提供摘要的条目抓取原文并提取正文主体",
    "description": """
InfoHub 正文提取
================
很多 RSS 只在 ``<description>`` 里给一两句摘要，读者点进详情页看不到内容。本模块
为这类条目按需抓取原文页面，用 trafilatura 剥掉导航、广告、推荐位，只保留正文，
净化后回写到条目上。

工作方式
--------
挂一个 ``usage = 'enricher'`` 的 component。采集流水线在条目落库后派发独立的
queue_job 任务来跑增强，不阻塞采集（R10.2）——正文提取要为每个条目额外发一次
HTTP 请求，同步做会让抓取轮次变得极慢。

只在需要时抓取
--------------
三个条件同时满足才会去抓：

* 源上 ``fulltext_enabled`` 为真（默认真，装了本模块就是想用它）
* 条目有 ``url``
* 现有正文长度小于源上的 ``fulltext_min_length`` 字段（默认 500 字符）

已成功或已失败的条目不会反复重试（``fulltext_state`` 记录处理结果）。管理员可以
在条目上手工触发重新提取。

出网约束
--------
抓原文一律走核心的 ``infohub.http`` component，因此自动继承 SSRF 防护、超时、
响应体积上限。两次请求之间按源上的 ``min_request_interval`` 休眠，避免把来源站
打崩。
    """,
    "author": "quick-sort@outlook.com",
    "website": "quick-sort@outlook.com",
    "category": "Productivity",
    "version": "19.0.1.0.0",
    "depends": ["infohub"],
    "external_dependencies": {
        "python": ["trafilatura"],
    },
    "data": [
        "views/infohub_source_views.xml",
        "views/infohub_item_views.xml",
    ],
    "license": "LGPL-3",
    "installable": True,
    "application": False,
    "auto_install": False,
}
