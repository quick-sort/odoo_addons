{
    "name": "InfoHub arXiv",
    "summary": "从 arXiv API 采集预印本，含分类码到学科的映射",
    "description": """
InfoHub arXiv
=============
从 arXiv 的 Atom API 采集预印本。

提供什么
--------
* ``transport = arxiv_api`` —— arXiv API 客户端，含分页、增量续传、全局限速
* ``provider = arxiv`` mapper —— arXiv 条目到 InfoHub 条目 + 论文载荷的映射
* classifier —— arXiv 分类码经映射表归到学科
* 161 条 ``infohub.topic.mapping`` 映射数据（学科树本身在 ``infohub_paper``）
* 若干板块预设，选一个就能建源

部署要求：必须配置 queue_job 通道容量
=====================================
arXiv 要求约 3 秒一次请求，而限速是**按来源方**计的：多个 arXiv 源（cs.LG、cs.CV、
math.AP……）是独立的源记录，``identity_key`` 只保证同一个源不并发，无法阻止它们同时
出网合计超速。

方案是"专用通道容量 1 + 请求最小间隔"（ADR-012）：本模块声明子通道
``root.infohub.arxiv``，并把该来源方的全部抓取任务派到这个通道。**通道容量不是数据库
字段，而是 odoo.conf 配置**，缺失则沿用默认，限速会**静默失效**::

    [queue_job]
    channels = root:4,root.infohub:2,root.infohub.arxiv:1

也可用环境变量 ``ODOO_QUEUE_JOB_CHANNELS``。漏配不会报错，但可能导致来源方封禁 IP。

为什么不自建令牌桶：容量 1 的通道已经把并发降为 1，此时"最小间隔"退化为单线程内的
sleep，正确性不依赖分布式协调。令牌桶只在"并发 N 且总速率受限"时才必要。
    """,
    "author": "quick-sort@outlook.com",
    "website": "quick-sort@outlook.com",
    "category": "Productivity",
    "version": "19.0.1.0.0",
    "depends": ["infohub_paper"],
    "external_dependencies": {
        # arXiv API 返回 Atom，用 feedparser 解析。与 infohub_rss 用的是同一个库，
        # 但不依赖那个模块——它提供的是 rss 传输，与本模块无关。
        "python": ["feedparser"],
    },
    "data": [
        "data/queue_data.xml",
        "data/infohub_topic_mapping_data.xml",
        "data/infohub_source_preset_data.xml",
    ],
    "license": "LGPL-3",
    "installable": True,
    "application": False,
    "auto_install": False,
}
