{
    "name": "InfoHub RSS/Atom",
    "summary": "通过 RSS/Atom 采集新闻与博客",
    "description": """
InfoHub RSS/Atom
================
为 InfoHub 提供 ``rss`` 传输维度与配套的通用 mapper。

新闻与博客绝大多数都提供 RSS/Atom，所以本模块一个人就覆盖了这两大类来源：
**新增一个常规 RSS 源不需要写任何代码**，建一条 ``infohub.source`` 记录即可
（或从预设里选一个）。

提供的实现
----------
* ``transport = rss`` —— 抓取与解析 feed，支持 ETag / Last-Modified 条件请求
* ``(provider = generic, transport = rss)`` mapper —— feed 条目到 InfoHub 条目
  的字段映射，含 HTML 净化
* classifier —— 把 feed 的 ``<category>`` 按名称宽松匹配到学科

只需要再加数据记录就能接入的场景
--------------------------------
任何返回标准 RSS 2.0 / Atom 1.0 / RDF 的地址。非标准或需要登录的站点才需要
写代码，那属于渠道模块。
    """,
    "author": "quick-sort@outlook.com",
    "website": "quick-sort@outlook.com",
    "category": "Productivity",
    "version": "19.0.1.0.0",
    "depends": ["infohub"],
    "external_dependencies": {
        "python": ["feedparser"],
    },
    "data": [
        "data/infohub_topic_mapping_data.xml",
        "data/infohub_source_preset_data.xml",
    ],
    "license": "LGPL-3",
    "installable": True,
    "application": False,
    "auto_install": False,
}
