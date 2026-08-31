==================
InfoHub 论文介质
==================

在 InfoHub 的三轴模型里提供 ``medium = paper`` 这一维。**只贡献介质轴**，不提供任何
采集实现——具体来源由渠道模块负责（``infohub_arxiv`` 等）。

提供什么
========

* ``infohub.paper`` —— 介质载荷表，继承 ``infohub.medium.payload``
* ``infohub.paper.author`` / ``infohub.journal`` —— 可跨条目复用的作者与期刊
* ``medium = paper`` component —— DOI 归一化与**跨源去重身份**
* arXiv 分类体系作为学科树种子数据（161 个节点，挂在 ``infohub.topic_academic`` 下）

跨源去重是介质的职责（ADR-006）
===============================

同一篇论文可能经 arXiv、期刊 RSS、Crossref 三条路进来。它们的 GUID、URL 完全不同，
唯一稳定的身份是 DOI（预印本则是 arXiv ID）。所以身份计算放在介质 component 里，而
不是散落在各个 provider——否则同一介质的 N 个来源会各写一份 DOI 归一化，跨源收敛
无法保证一致。

``identity()`` 的优先级::

    1. mapper 显式给的 doi
    2. mapper 显式给的 arxiv_id
    3. 从 url / 摘要 / 正文里正则捞 DOI
    4. 从 arxiv.org 链接里捞 arXiv ID
    5. 都失败 -> None（不参与跨源去重）

第 3 步是关键设计
-----------------

``infohub_rss`` 的通用 mapper 不知道 DOI 是什么，它只给出 title / url / summary。而
期刊 RSS 通常在链接或描述里带 DOI。第 3 步让**一个期刊 RSS 源只要把介质设成「论文」
就能参与论文去重，不需要为它写任何 provider 代码**。

这是把去重放在介质轴而非来源轴的直接收益，已有验收测试：同一篇论文经 arXiv API 与
期刊 RSS 两路进入，收敛为一条。

第 5 步返回 None 而不是退回 URL
-------------------------------

找不到稳定身份时不参与跨源去重。退回规范化 URL 看似"更彻底"，但 arXiv 与期刊的 URL
本来就不同，合并不了；而一旦规则放宽就有错误合并的风险。**宁可漏合并，不可错合并。**

DOI 归一化的坑
==============

``normalize_doi`` 先用正则宽匹配，再在 Python 里截断非 ASCII 字符、剥掉尾部标点。
纯正则很难写对右边界——最初的版本只排除了 ASCII 标点，``见 10.1038/xxx。`` 会把中文
句号一起吞进 DOI，导致同一个 DOI 算成两个。测试里有 14 个边界用例覆盖这类情况。

arXiv ID 归一化会**去掉版本号**：v1 与 v3 是同一篇论文，应收敛为一条。

作者去重只做保守归一化
======================

压缩空白、去首尾标点、转小写后比对。**不做启发式合并**（不动姓名顺序、不展开缩写）
——把两位同名作者错并成一个人比不合并更糟。需要精确消歧应接 ORCID（已留字段）。

只存 PDF 链接（R11.2）
======================

``pdf_url`` 只存链接，不下载、不进 ``ir.attachment``、不进 filestore。若将来要存，
应进 ``ir.attachment``（走 filestore）而非数据库字段。

对 design.md 的一处有意偏离
===========================

design.md 提到"用 ``related`` 把 DOI 提到 ``infohub.item`` 上"来缓解载荷表的 join
成本。**实际做不到**：``related`` 需要单记录路径，而载荷是 One2many（一对一由唯一
约束保证，类型上仍是 o2m），``related="paper_ids.doi"`` 不成立。要做成 related 就得在
item 上再放一个 Many2one 反向指回载荷，等于把一对一关系存两份，更容易不一致。

改用的方案：给 ``infohub.paper`` 自己一套列表/搜索视图和菜单，并在载荷表上把
``title`` / ``published_at`` / ``source_id`` / ``state`` 做成 ``store=True`` 的
related。论文场景本来就更常按论文维度浏览（按作者、按期刊、按 DOI 找），列表页也
不需要联表。

学科树为什么放这里
==================

树放本模块而不是 ``infohub_arxiv``（ADR-014）：树是**共享**的——将来
``infohub_pubmed`` 的生物医学论文同样归到 ``q-bio`` 之下；而 ``cs.LG -> topic``
这种**编码映射**是 arXiv 专有的，放在 ``infohub_arxiv``。

学科的 ``code`` 直接用 arXiv 的分类码：它天然稳定、全球唯一，比自造编码好。
``infohub.topic_academic`` 这个根节点的 xmlid 是核心的对外契约，不要改名。

测试
====

见 ``.kiro/specs/infohub/stage5_test.py`` 第 1–4 节：学科树与映射、DOI/arXiv ID
归一化的 20 个边界用例、身份计算的 10 种情形、载荷落库与作者/期刊解析。
