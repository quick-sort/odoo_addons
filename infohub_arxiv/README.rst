==============
InfoHub arXiv
==============

从 arXiv 的 Atom API 采集预印本。

提供什么
========

* ``transport = arxiv_api`` —— arXiv API 客户端，含分页、增量续传、限速
* ``provider = arxiv`` mapper —— arXiv 条目到 InfoHub 条目 + 论文载荷的映射
* classifier —— arXiv 分类码经映射表精确归到学科
* 161 条 ``infohub.topic.mapping`` 映射数据（学科树本身在 ``infohub_paper``）
* 7 个板块预设，选一个就能建源

部署要求：必须配置 queue_job 通道容量
=====================================

arXiv 要求约 3 秒一次请求，而**限速是按来源方计的**：多个 arXiv 源（cs.LG、cs.CV、
math.AP……）是独立的源记录，``identity_key`` 只保证同一个源不并发，无法阻止它们同时
出网合计超速。

方案是"专用通道容量 1 + 请求最小间隔"（ADR-012）。本模块声明子通道
``root.infohub.arxiv`` 并把该来源方的全部抓取任务派到它。**通道容量不是数据库字段，
而是 odoo.conf 配置**::

    [queue_job]
    channels = root:2,root.infohub:2,root.infohub.arxiv:1

也可用环境变量 ``ODOO_QUEUE_JOB_CHANNELS``。**漏配不会报错，但限速会静默失效**，
可能导致 arXiv 封禁 IP。测试脚本里有一项专门断言这行配置存在。

为什么不自建令牌桶：容量 1 的通道已经把并发降为 1，此时"最小间隔"退化为单线程内的
sleep，正确性不依赖分布式协调。令牌桶只在"并发 N 且总速率受限"时才必要。

限速的两层
----------

1. **任务级** —— 本源的任务派到容量 1 的通道，全局串行
2. **请求级** —— 单次任务内翻页之间 sleep ``min_request_interval``（默认 3 秒）

增量策略
========

arXiv 不支持条件请求（无 ETag / Last-Modified），所以走**发布时间水位线**：按
``submittedDate`` 降序翻页，一旦遇到不新于游标的条目就停止翻页。稳定状态下每轮只取
到新增的那几条。

首轮（无游标）翻到 ``arxiv_max_pages``（默认 10）页为止，剩下的留给下一轮——不在一个
任务里把历史全抓完。

分页 URL 用正规的 URL 拆解与重组，而不是字符串拼 ``&start=``：端点里可能已经带了
``?`` 或已经带了 ``start``。同时强制 ``sortBy=submittedDate&sortOrder=descending``,
增量策略依赖这个顺序。

一个踩过的坑：不要给 component 的方法起名 ``_abstract``
=======================================================

mapper 里原本有个 ``@staticmethod def _abstract(entry)`` 用来提取论文摘要。
``_abstract`` 是 component 框架用来判断"组件是否抽象"的**类属性**
（``AbstractComponent._abstract``），定义同名方法会把它从布尔值覆盖成函数对象，
函数是真值，于是 ``ComponentRegistry.lookup`` 把这个 component 当抽象组件直接排除。

表现是"明明写了 mapper 却报 ``NoComponentError``"，而且静态检查完全看不出来。已改名为
``_abstract_text``。其他保留名：``_name`` / ``_inherit`` / ``_usage`` / ``_collection``
/ ``_apply_on`` / ``_register`` / ``_module``。

关于 ``_queue_channel`` 里的 if 分支
====================================

``models/infohub_source.py`` 的 ``_queue_channel()`` 里有
``if self.transport == "arxiv_api"``。项目约束说"调用方不得出现来源判断分支"，但那条
约束针对**核心与流水线调用方**——它们必须靠 component 解析。这里是卫星模块在自己的
模型扩展里判断"这个源是不是我的"，是 Odoo ``_inherit`` 覆盖的标准形态，不加守卫就会
劫持所有源的通道。

不过这确实暴露了核心的一个可改进点：``_queue_channel()`` 没有委托给 transport
component，而"用哪个队列通道"本质上是**传输方式**的属性。已作为抽象复核点的发现记录在
``.kiro/specs/infohub/progress.md``，是否改核心留待决定。**当前实现不需要改核心即可
正确工作。**

依赖
====

``feedparser``（arXiv API 返回 Atom）。与 ``infohub_rss`` 用同一个库，但**不依赖那个
模块**——它提供的是 ``rss`` 传输，与本模块无关。

注意本项目的容器镜像 ``odoo:19.0`` **不自带** feedparser，需要额外安装。

测试
====

见 ``.kiro/specs/infohub/stage5_test.py`` 第 5–8 节：mapper 字段映射、分类归类、
限速通道路由、端到端采集流水线、**跨源收敛验收**。
