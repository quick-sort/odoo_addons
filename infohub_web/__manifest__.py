{
    "name": "InfoHub 网页采集",
    "summary": "无 RSS 站点的选择器抓取，接入新站点只需加一条配置记录",
    "description": """
InfoHub 网页采集
================
为没有 RSS 的站点提供采集能力。核心机制是**把爬虫做成配置而不是代码**：

新增一个结构常规的站点 = 加一条 ``infohub.web.profile`` 记录，**零代码**。
只有需要 JS 渲染、登录、反爬对抗的站点才需要写 component，那属于渠道模块。

这是"扩展性主要来自数据，模块数随来源数次线性增长"（ADR-018 / N10）在网页来源上的
落点——否则每个博客一个模块，模块数会线性爆炸。

两阶段抓取
----------
1. **列表页** —— 按分页方式翻页，用 CSS 选择器取出条目链接
2. **详情页** —— 逐个抓取并用选择器提取字段

列表页本身就含全文的站点可以设成"仅列表页"模式，跳过第二阶段。

只抓新的
--------
翻完列表页后，先把**已入库的链接剔除**，再去抓详情页。没有这一步，每轮都会把所有
详情页重抓一遍——这是网页采集与 RSS 最大的成本差异。

选择器用 CSS 而非 XPath
-----------------------
用 BeautifulSoup + soupsieve（都是容器已有的库）。CSS 选择器对配置作者友好得多，
而且这两个库不需要额外安装（``cssselect`` 缺失，所以 ``lxml.cssselect`` 不可用）。

选择器在**保存时**就用 soupsieve 编译校验，坏选择器不会跑到采集流水线里才炸。
    """,
    "author": "quick-sort@outlook.com",
    "website": "quick-sort@outlook.com",
    "category": "Productivity",
    "version": "19.0.1.0.0",
    "depends": ["infohub"],
    "external_dependencies": {
        # 注意用 PyPI 包名而不是 import 名：dateutil 的包名是 python-dateutil，
        # 写成 dateutil 会让 Odoo 报"不是有效的 PyPI 包名"
        "python": ["beautifulsoup4", "soupsieve", "lxml", "python-dateutil"],
    },
    "data": [
        "security/ir.model.access.csv",
        "views/infohub_web_profile_views.xml",
        "views/infohub_source_views.xml",
        "views/infohub_menus.xml",
        "data/infohub_web_profile_data.xml",
        "data/infohub_source_preset_data.xml",
    ],
    "license": "LGPL-3",
    "installable": True,
    "application": False,
    "auto_install": False,
}
