{
    "name": "InfoHub 论文介质",
    "summary": "论文的结构化字段、DOI 去重、学科树",
    "description": """
InfoHub 论文介质
================
在 InfoHub 的三轴模型里提供 ``medium = paper`` 这一维。**只贡献介质轴**，不提供任何
采集实现——具体来源由渠道模块负责（``infohub_arxiv`` 等）。

提供什么
--------
* ``infohub.paper`` —— 介质载荷表，继承 ``infohub.medium.payload``
* ``infohub.paper.author`` / ``infohub.journal`` —— 可跨条目复用的作者与期刊
* ``medium = paper`` component —— 负责 DOI 归一化与**跨源去重身份**
* arXiv 分类体系作为学科树种子数据

跨源去重是介质的职责（ADR-006）
-------------------------------
同一篇论文可能经 arXiv、期刊 RSS、Crossref 三条路进来。它们的 GUID、URL 完全不同，
唯一稳定的身份是 DOI（预印本则是 arXiv ID）。所以身份计算放在介质 component 里，
而不是散落在各个 provider：

1. mapper 显式给出的 ``doi`` / ``arxiv_id``
2. 都没有时，从 url / 摘要 / 正文里用正则捞 DOI 或 arXiv ID

第 2 步让**通用 RSS mapper 也能参与论文去重**——期刊 RSS 通常在链接或描述里带 DOI，
而 ``infohub_rss`` 的通用 mapper 并不知道 DOI 是什么。这是把去重放在介质轴而非来源轴
的直接收益。

找不到任何稳定身份时返回 None，即**不参与跨源去重**——宁可漏合并，不可错合并。

只存 PDF 链接（R11.2）
----------------------
``pdf_url`` 只存链接，不下载、不进 ``ir.attachment``、不进 filestore。
    """,
    "author": "quick-sort@outlook.com",
    "website": "quick-sort@outlook.com",
    "category": "Productivity",
    "version": "19.0.1.0.0",
    "depends": ["infohub"],
    "data": [
        "security/ir.model.access.csv",
        "data/infohub_topic_arxiv_data.xml",
        "views/infohub_journal_views.xml",
        "views/infohub_paper_author_views.xml",
        "views/infohub_paper_views.xml",
        "views/infohub_item_views.xml",
        "views/infohub_menus.xml",
    ],
    "license": "LGPL-3",
    "installable": True,
    "application": False,
    "auto_install": False,
}
