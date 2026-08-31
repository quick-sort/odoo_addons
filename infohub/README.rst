=======
InfoHub
=======

在线信息聚合的核心模块：把 RSS 新闻、博客、学术论文、社交内容汇集成统一的、
可按学科/标签订阅的信息流。

本模块只提供核心层与扩展点，**自身不含任何具体的采集实现**。要真正抓到内容，
需要装至少一个传输模块（例如 ``infohub_rss``）。

三轴组合模型
============

信息源由三个正交维度组合定义::

    infohub.source = medium × transport × provider
                       介质      传输       来源

============  ==========================================  ============================
维度          决定什么                                    由谁扩展
============  ==========================================  ============================
``medium``    条目字段语义、扩展数据结构、去重身份算法    介质模块（``infohub_paper``）
``transport`` 怎么拿到字节、怎么做增量                    传输模块（``infohub_rss``）
``provider``  该来源特有的字段映射                        渠道模块（``infohub_arxiv``）
============  ==========================================  ============================

三个维度各自用 ``_selection_add`` 扩展，**互不继承**。核心的采集编排里没有任何
来源判断分支。

组合的合法性不靠白名单维护，而是在约束里尝试解析三个必选 usage
（``transport`` / ``medium`` / ``mapper``）对应的 component，任一解析不到即拒绝。
装上新模块就自动放开新组合。

写一个新的采集实现
==================

传输维度::

    from odoo.addons.component.core import AbstractComponent, Component

    class MyTransport(Component):
        _name = "infohub.mytransport.transport"
        _inherit = "infohub.transport.base"
        _transport = "mytransport"

        def fetch(self):
            http = self.component(usage="http")   # 必须走这里，别直接用 requests
            response = http.get(
                self.source.endpoint,
                etag=(self.source.cursor_state or {}).get("etag"),
            )
            if response is None:
                return [], None                   # 304，内容未变
            entries = self._parse(response.content)
            return entries, http.cursor_headers(response)

注意 component 用 ``_inherit`` **字符串**声明继承，不要用 Python 类继承——
框架用 ``_inherit`` 建立注册表关系，Python 继承不算数。

安装与部署
==========

依赖
----

``base``、``mail``、``component``、``queue_job``。

queue_job 通道容量（重要）
--------------------------

本模块声明了 queue_job 通道 ``root.infohub``。**通道容量不是数据库字段，而是
odoo.conf 配置**，缺失则沿用默认 ``root:1``（全局只有一个并发）::

    [queue_job]
    channels = root:4,root.infohub:2

也可以用环境变量::

    ODOO_QUEUE_JOB_CHANNELS=root:4,root.infohub:2

需要遵守来源方限速的渠道模块会在本通道下再开子通道并要求容量 1，例如
``infohub_arxiv`` 需要::

    channels = root:4,root.infohub:2,root.infohub.arxiv:1

**漏配这一行不会报错，但限速会静默失效**，可能导致来源方封禁 IP。

开发期允许访问私网地址
----------------------

出于 SSRF 防护，源的端点默认不允许指向私网、环回、链路本地地址。本地起一个
测试服务器时，可以临时打开开关（系统参数）::

    infohub.allow_private_urls = True

**生产环境不要开。** 打开后任何能创建信息源的用户都可以让 Odoo 服务器去探测
内网，包括云环境的元数据服务（169.254.169.254）。

安全说明
========

* **SSRF**：端点由用户输入、由服务端请求。校验在 ``infohub/url_guard.py``，
  出网统一走 ``infohub.http`` component，重定向逐跳复检。残留的 DNS rebinding
  风险见 ``url_guard.py`` 的模块文档。
* **XSS**：条目正文是第三方 HTML 且会渲染到公开页面。字段用
  ``sanitize=True``；QWeb 模板一律 ``t-out``，禁止 ``t-raw``。
* **凭证**：独立的 ``infohub.credential`` 模型，仅 ``infohub.group_manager``
  有 ACL。信息源本身对读者可读（他们要按源订阅），所以凭证绝不能放在源上。
* **越权**：``infohub.subscription`` 与 ``infohub.item.read`` 有
  ``user_id = user.id`` 记录规则。条目本身的记录规则只按 ``state`` 与
  ``access_level`` 过滤，个性化在控制器层完成——这个取舍的前提是内容都是公开
  网页信息，接入机密源时必须重新评估。

权限
====

====================  ========  ==================================================
组                    类型      能做什么
====================  ========  ==================================================
``group_reader``      portal    读已发布的公开条目；管自己的订阅与阅读状态
``group_user``        内部      后台查看条目、信息源、抓取日志
``group_moderator``   内部      人工标黑、改条目状态、管标签
``group_manager``     内部      管信息源、凭证、学科词表
====================  ========  ==================================================

设计文档
========

完整的需求、设计、决策记录在 ``.kiro/specs/infohub/``：

* ``requirements.md`` —— 需求 R1–R13、非功能需求 N1–N10
* ``design.md`` —— 架构与数据模型
* ``decisions.md`` —— **被否决的方案与理由，改设计前必读**
* ``tasks.md`` —— 任务与阶段
* ``progress.md`` —— 进度与交接状态
