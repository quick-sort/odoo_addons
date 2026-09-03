# InfoHub 设计决策记录（ADR）

本文件记录**被否决的方案及其理由**。`design.md` 说明"是什么"，本文件说明"为什么不是别的"。

> 修改本文件的规则：不删除已有条目。决定被推翻时，把原条目标记为"已被 ADR-NNN 取代"，并新增条目说明推翻的理由。ADR-005 是一个例子。

---

## ADR-001 用 component 模式做多态，而非模型继承或 if/elif 分发

**决定** 采集流水线的所有可变部分都由 `component` 模块的 component 提供，`infohub.source` 继承 `collection.base`。

**否决方案**
- *`if source_type == "rss": ... elif ...`* —— 每加一个来源都要改核心，违背 N8。
- *Odoo 模型继承（每种源一个模型）* —— 源记录要分表，统一调度、统一日志、统一去重全部要写多份。
- *Selection + 方法名约定（`_fetch_rss`）* —— 无法让第三方模块覆盖已有实现，也无法多个模块各挂一个增强器。

**影响** 核心依赖 `component`。调用方代码中不出现任何来源判断分支。

---

## ADR-002 三轴组合（medium × transport × provider），而非单继承树

**决定** `infohub.source` 由三个独立 Selection 组合定义。渠道模块只贡献 provider 映射，传输来自传输模块，介质字段来自介质模块，三者之间无继承关系。

**背景** 最初设计成"`infohub_paper` 下挂各期刊"的树。但论文可以经 REST API（arXiv）、RSS（Nature 新刊）、HTML 爬取（无 API 的期刊站）三种完全不同的传输方式进入——内容类型与传输方式是正交的两个轴。

**否决方案**
- *单父继承树（paper → 各期刊）* —— 期刊 RSS 的条件请求、ETag、编码嗅探会与 `infohub_rss` 里的实现重复一份。
- *component 跨轴 `_inherit`（期刊 mapper 继承 RSS mapper）* —— 是伪装成组合的继承，轴数增加时组合爆炸。轴**内**继承是允许的。

**影响** 三个维度各自用 `_selection_add` 扩展；一个模块原则上只在一个轴上贡献实现（N9）。

---

## ADR-003 时间线用拉取式（query-time），否决扇出式（fan-out on write）

**决定** 条目只存一份，用户时间线由其订阅动态拼 domain。

**否决方案** *为每个「用户 × 命中条目」写一行* —— 200 用户 × 50 万条目 = 10⁸ 行；且用户改一次订阅就要回溯重算历史扇出；新增订阅维度要改扇出逻辑。

**影响** 改订阅零成本、立即生效（R7.5）。代价是未读数不能直接 count，需要 ADR-004 的水位线。

---

## ADR-004 per-user 状态用稀疏交互表 + 订阅水位线

**决定** `infohub.item.read` 只为**实际发生过交互**的 (user, item) 建行；每个订阅上存 `last_read_at` 水位线，未读 = 命中 domain 且 `published_at > last_read_at` 且不在已读表中。

**否决方案**
- *在 `infohub.item` 上放 `is_read` 布尔字段* —— 多人共享时语义错误：一个人读了就对所有人变已读。这是最早的设计，在确认多用户需求后废弃。
- *为每个用户预生成全部已读行* —— 退化为 ADR-003 否决的扇出。

**影响** 已读表大小与实际阅读量成正比，不随时间线性膨胀（R8.2）。

---

## ADR-005 介质特有字段分表存放，不加在核心条目表上

**决定** 介质字段放各自的载荷表（`infohub.paper` 等），继承 `infohub.medium.payload` 抽象契约，与 `infohub.item` 一对一。

**背景** 这条**推翻了本项目早期的决定**。早期结论是"论文字段直接加到 `infohub.item` 上，Odoo 表有上百列很常见"。在确认了(a)采用组合模型 ADR-002、(b)介质种类会持续增加（论文、社交、未来视频/专利/数据集）之后，取舍点移动了。

**否决方案**
- *单表加列* —— 核心表随介质数量膨胀；卸载介质模块会在核心表留下孤儿列；各介质模块不能完整拥有自己的 schema。
- *`_inherits` 委托继承（`infohub.paper` 委托到 `infohub.item`）* —— 会要求以创建 `infohub.paper` 为入口，与"流水线统一创建 `infohub.item`"的方向相反。

**影响** 显示介质字段需要 join；缓解手段是在 `infohub.item` 上为最常用的一两个字段（如 DOI）开 `related`。

---

## ADR-006 去重身份的计算归属介质维度

**决定** `identity_key` 由 `medium` component 的 `identity()` 计算，核心不硬编码任何身份规则。

**背景** 论文的身份是归一化 DOI（同一篇经 arXiv、期刊 RSS、Crossref 三路进来须收敛为一条）；新闻的身份是 GUID 或规范化 URL。差异属于介质，不属于来源。

**否决方案** *各 provider 各自实现去重* —— 同一介质的 N 个来源会各写一份 DOI 归一化，且跨源收敛无法保证一致。

---

## ADR-007 `provider` 必填且默认 `generic`，不允许留空

**决定** `provider` 是 required 字段，核心提供默认值 `generic`。mapper 的匹配键是 `(provider, transport)`。

**背景** 这是 `component` 框架的一个陷阱：`WorkContext.component()` 匹配到多个候选时抛 `SeveralComponentError`，而它内置的消歧只按 collection 和 model（见 `component/core.py` 的 `_filter_components_by_collection` / `_filter_components_by_model`），在三轴场景下都无法消歧。

**否决方案**
- *provider 留空表示"通用"* —— 通用 RSS mapper（provider 为空）与期刊 mapper 会同时命中同一个源，直接抛异常。
- *用 `many_components()` 取全部再按特异度排序挑一个* —— 可行但把消歧逻辑散进核心，且特异度规则需要额外约定。

**影响** `infohub_rss` 提供 `(generic, rss)`，`infohub_web` 提供 `(generic, web)`，互不冲突；每个源恰好命中一个 mapper。

---

## ADR-008 组合合法性由"可解析性"定义，不维护白名单

**决定** `@api.constrains` 里尝试解析 transport / medium / mapper 三个 component，任一 `NoComponentError` 即拒绝并提示可能缺失的模块。

**否决方案** *维护一张合法三元组白名单表* —— 白名单与实际实现是两处需要同步的真相，装卸模块时必然漂移。

**影响** 装上新模块即自动放开新组合，无第二处需维护。

---

## ADR-009 审核状态机与人工标黑在核心，只有规则引擎在 `infohub_filter`

**决定** `state` 状态机、`infohub.blocklist`、`_moderate()` 钩子在核心；`infohub.rule` 规则引擎在 `infohub_filter`，通过覆盖 `_moderate()` 介入。

**背景** portal 的记录规则依赖 `item.state`（N7），核心不能依赖一个可选模块才能保证访问控制正确。

**否决方案**
- *整套审核都放 `infohub_filter`* —— 核心的安全边界依赖可选模块，卸载后 portal 可见性失控。
- *整套审核都放核心* —— 规则引擎是可选能力，放核心会让不需要它的部署也承担复杂度。

**影响** 核心 `_moderate()` 默认直接发布；卸载 `infohub_filter` 后核心仍能正常工作（R6.4，已列为验收项 4.7）。

---

## ADR-010 HTTP 客户端在核心，不单开 `infohub_http_api` 模块

**决定** SSRF 防护、超时、响应体积上限、重定向复检、条件请求由核心的 HTTP 组件基类提供。

**背景** `infohub_rss`、`infohub_web`、`infohub_arxiv` 都要出网；而 N3/N5 的安全要求本就是核心职责，核心无论如何都要有 HTTP 层。

**否决方案** *单开传输基础模块* —— 会导致核心的安全约束依赖可选模块，且所有传输模块都得依赖它，等于变相的必选依赖。

---

## ADR-011 portal 读者自助注册

**决定** `infohub_website` 依赖 `auth_signup`，开放自助注册 + 邮箱验证；新用户自动获得一组默认订阅。

**否决方案** *管理员邀请制* —— 用户明确要求自助注册。

**影响** 需注册滥用防护（邮箱验证必过、频率限制）。自助注册**不放宽任何数据可见性**，权限完全由 §6.2 记录规则约束。默认订阅是为了避免首屏时间线为空（R9.6）。

---

## ADR-012 arXiv 限速用「专用通道容量 1 + 最小请求间隔」，不自建令牌桶

**决定** `infohub_arxiv` 声明子通道 `root.infohub.arxiv`，部署时配置容量 1；transport component 内两次请求间按 `min_request_interval`（默认 3.0 秒）休眠。

**背景** 限速是**按来源方**计的。会存在多个 arXiv 源（cs.LG、cs.CV、math.AP…），它们是独立的源记录；`identity_key` 只保证同一个源不并发，无法阻止多个 arXiv 源同时出网合计超速。

**否决方案**
- *仅靠 `identity_key` 同源串行 + sleep* —— 上述原因，多源并发时失效。
- *DB 令牌桶 / `pg_advisory_lock` 分布式限流* —— 容量 1 已把并发降为 1，此时最小间隔退化为单线程 sleep，正确性不依赖分布式协调。令牌桶只在"并发 N 且总速率受限"时才必要，arXiv 不属此情形。

**影响** arXiv 抓取整体串行——但在 3 秒/请求约束下本来就无法并行。**通道容量是 odoo.conf 配置（`[queue_job] channels = root:4,root.infohub.arxiv:1`），不是 DB 字段；漏配则限速静默失效**，必须写入模块 README。同一模式可复用于任何有限速要求的来源方。

---

## ADR-013 不做站内通知

**决定** 对外触达只有 `infohub_digest` 的摘要邮件。

**否决方案** *`mail.thread` 站内通知 / bus 实时推送* —— 用户明确不要。

---

## ADR-014 学科树与外部编码映射分离

**决定** 学科树（`infohub.topic`，arXiv 分类体系为种子）作为数据放 `infohub_paper`；`cs.LG → topic` 这类编码映射（`infohub.topic.mapping`）放各渠道模块。

**背景** 树是共享的（`infohub_pubmed` 可复用同一棵树），映射是各来源方专有的。

**否决方案** *树和映射都放渠道模块* —— 多个渠道会各建一棵树，跨学科订阅无法统一。

**影响** 接入新学科领域只需增加映射数据，不改代码（R4.5）。

---

## ADR-015 `infohub.item` 的记录规则只按 `state` 和 `access_level`，不按订阅

**决定** 记录规则用索引字段过滤；个性化（订阅 domain）放在控制器里，属于展示逻辑。

**背景** 按 m2m 订阅做记录规则需要联表，在几十万行上退化为慢查询（N1）。

**安全论证** 这些是公开网页内容，读到未订阅的条目不构成机密泄露。`access_level = internal` 的源对 portal 不可见，为将来接付费/内部源留出口。**若后续引入真正机密的源，此决定必须重新评估。**

**影响** 真正需要隔离的是 `infohub.subscription` 与 `infohub.item.read`，它们必须有 `user_id = user.id` 的记录规则（N7）——漏掉会导致用户可读改他人订阅。

---

## ADR-016 只保存 PDF 的 URL，不下载文件

**决定** `infohub.paper.pdf_url` 存链接；不下载、不进 `ir.attachment`、不进 filestore。

**否决方案** *下载 PDF 存 `ir.attachment`* —— 用户明确要求本期不存。**注意**：若后续要存，应进 `ir.attachment`（走 filestore）而非数据库字段。

---

## ADR-017 本期不桥接 `knowledge_base`，Twitter 暂缓

**决定** 不做 `infohub_knowledge`。`infohub_social` + `infohub_twitter` 保留设计位置但不实现。

**背景** Twitter/X 官方 API 免费档读取额度基本不可用于采集，Basic 档需付费；用户访问权限未确定。

**影响** 介质层设计已为社交内容预留（ADR-002 的三轴对新介质开放）。若改做开放平台（Mastodon / Bluesky），复用同一介质层。

---

## ADR-018 模块边界由"独立依赖 / 独立服务 / 独立解析代码 / 独立 UI 面"划定

**决定** 新增模块的判定标准：
| 情况 | 做法 | 模块数 |
|---|---|---|
| 又一个 RSS 地址 | 建一条 `infohub.source` 记录 | 0 |
| 新网站，HTML 结构常规 | 建一条 `infohub.web.profile` 记录 | 0 |
| 一批同质来源（如 20 个期刊 RSS） | 一个模块 + 20 条数据记录 | 1 |
| 网站需 JS 渲染 / 登录 / 反爬 | 在对应渠道模块加一个 component | 0 |
| 新 API（独立认证、分页、字段结构） | 建一个渠道模块 | 1 |
| 引入可选的重型 Python 依赖 | 单独模块 | 1 |

**否决方案** *按"这是另一个功能"来划模块* —— 会导致一个网站一个模块，来源增长时模块数线性爆炸。

**影响** 扩展性主要来自**数据**而非代码，模块数随来源数次线性增长（N10）。故设计中**没有** `infohub_news_rss` / `infohub_blog_html` 这类模块——它们是 `infohub_rss` / `infohub_web` 的数据记录。

---

## ADR-019 用 `infohub.source.preset` 把三个维度对管理员隐藏

**决定** 各渠道模块以 `noupdate="1"` 数据文件提供源预设；管理员建源时选预设即自动填好三轴与端点。

**背景** 三个 Selection 对管理员是认知负担，且容易配出无效组合。

**影响** 日常"加一个期刊/板块"退化为加一条数据记录，是 ADR-018 落地的具体机制。

---

## ADR-020 已知偏离：`infohub_arxiv` 同时贡献 transport 与 provider 两个维度

**决定** 接受这一偏离，暂不抽象共用的 API 分页/限流层。

**背景** N9 要求一个模块只在一个轴上贡献实现。但 arXiv 的分页与续传语义属于它自己，`transport = arxiv_api` 无法归入通用 HTTP 传输。

**否决方案** *预先建立通用 API 传输抽象* —— 目前只有一个 API 类来源，抽象缺少第二个样本，属于过早抽象。

**复审触发条件** `infohub_pubmed` 落地时，若确认分页/限流代码重复，则把共用部分上提为独立基类。**此偏离已按 N9 要求登记。**


---

## ADR-021 三轴抽象复核通过（阶段 5 检验结论）

**背景** design.md §10 与验收项 5.12 定下的检验标准：接入 arXiv 时如果需要修改
`infohub` 核心，就说明维度切分错了。阶段 5 引入了第一个新介质（paper）、第一个真正的
provider mapper、第一个介质载荷表——是这套抽象最直接的压力测试。

**结论：通过。整个阶段 5 未修改核心一行代码。**

实证：`infohub/` 下最后修改的文件时间戳是 11:28，而 `infohub_paper/` 与
`infohub_arxiv/` 的最早文件是 23:03。核心在阶段 5 全程未被触碰。

各模块严格只贡献自己那一轴：

| 模块 | 贡献的轴 | 具体 |
|---|---|---|
| `infohub_paper` | medium | `medium=paper` 取值 + 载荷表 + 介质 component + 学科树数据 |
| `infohub_arxiv` | transport + provider | `arxiv_api` 传输、`arxiv` mapper、classifier、映射与预设数据 |

被验证有效的三处设计：

1. **去重身份归介质轴（ADR-006）确实带来了预期收益。** 期刊 RSS 源只要把介质设成
   paper，就能靠 DOI 与 arXiv 源收敛为一条——而 `infohub_rss` 的通用 mapper 完全不知道
   DOI 是什么，一行代码没改。这是"零代码接入一类新来源"的真实兑现。
2. **载荷表分离（ADR-005）在实践中站得住。** mapper 在 payload 里随意放介质专用键，
   核心的 `_item_vals` 按字段白名单过滤掉它们，介质 component 的 `payload_vals` 再消费
   ——mapper 不需要知道载荷表长什么样。
3. **`provider` 必填默认 `generic`（ADR-007）避免了实际冲突。** arXiv mapper 的匹配键
   是 `(arxiv, arxiv_api)`，与 `(generic, rss)` 天然不撞。

---

## ADR-022 已知偏离：`_queue_channel()` 未委托给 transport component

**发现于** 阶段 5 抽象复核。

**现状** `infohub_arxiv` 需要把抓取任务路由到专用限速通道，做法是在自己的
`infohub.source` 扩展里覆盖 `_queue_channel()` 并加守卫：

```python
def _queue_channel(self):
    if self.transport == "arxiv_api":
        return ARXIV_CHANNEL
    return super()._queue_channel()
```

**为什么这不违反"调用方不得出现来源判断分支"** 那条约束针对**核心与流水线调用方**
——它们必须靠 component 解析。这里是卫星模块在自己的模型扩展里判断"这个源是不是我的"，
是 Odoo `_inherit` 覆盖的标准形态；不加守卫会劫持所有源的通道。

**但确实是一处设计气味** "用哪个队列通道"本质上是**传输方式**的属性，理应由 transport
component 提供，而不是让每个渠道模块各写一个 if。理想形态是核心改成：

```python
def _queue_channel(self):
    with self.work_on() as work:
        return work.component(usage="transport").queue_channel()
```

**决定** **暂不改核心。** 理由：

* 当前实现不需要改核心即可正确工作，改动属于优化而非修复
* 只有一个渠道模块需要专用通道，抽象缺少第二个样本
* 复核点的目的是**发现**问题，不是强行消除每一处不完美

**复审触发条件** 出现第二个需要专用通道的来源方（如 `infohub_pubmed`）时，把
`queue_channel()` 上提为 `infohub.transport.base` 的一个方法，核心的 `_queue_channel()`
改为委托。届时两个渠道模块的 if 分支一并删除。

---

## ADR-023 component 的方法名不得与框架保留属性冲突

**背景** arXiv mapper 里原本有个 `@staticmethod def _abstract(entry)` 用于提取论文
摘要。结果该 mapper 完全无法被解析，报 `NoComponentError: No component found for
usage 'mapper'`。

**原因** `_abstract` 是 component 框架用来判断"组件是否抽象"的**类属性**
（`AbstractComponent._abstract = True` / `Component._abstract = False`）。定义同名方法
把它从布尔值覆盖成函数对象，函数是真值，于是 `ComponentRegistry.lookup` 的
`if not component._abstract` 过滤把这个 component 当抽象组件直接排除。

**决定** component 类里禁止使用以下方法名，它们是框架保留的类属性：

`_abstract`、`_name`、`_inherit`、`_collection`、`_usage`、`_apply_on`、
`_register`、`_module`

已改名为 `_abstract_text`。

**为什么值得记一条 ADR** 这类错误静态检查、类型检查、编译全都发现不了，只有实际
解析 component 时才暴露，而报错信息（"找不到 mapper"）与真实原因（"方法名撞了"）
毫无关联，排查成本极高。已同时写进 steering，让后续开发不再重踩。


---

## ADR-024 SSRF 校验拆成"保存时快速校验"与"请求时完整校验"

**发现于** 阶段 6。原实现在 `infohub.source` 的 `@api.constrains("endpoint")` 里调用
`assert_url_allowed()`，而那个函数会做 DNS 解析。

**问题有两个，第二个更严重**

1. 主机名暂时不可解析的合法配置根本存不下来（内部 DNS、站点临时故障、还没上线的域名）
2. **在 `@api.constrains` 里发网络请求**，等于让每次保存源都阻塞在 DNS 上。解析器慢或
   不可达时会拖住整个事务——这是把外部网络的可用性引入了数据库写路径

**决定** `assert_url_allowed(url, allow_private=False, resolve=True)` 增加 `resolve`
参数，拆成两级：

| 时机 | 调用方 | 检查内容 |
|---|---|---|
| 保存时 | `infohub.source._check_endpoint` | scheme、主机名存在性、**字面量 IP**、已知本机名（`localhost` / `*.localhost` 等）。**不发 DNS** |
| 请求时 | `infohub.http._request` | 完整 DNS 解析 + 全部解析结果校验 + 重定向逐跳复检 |

**安全属性未被削弱** 真正的防护点一直是"发起请求时"。任何实际出网都经过
`infohub.http`，它对每一跳都做完整解析校验。保存时的解析本来也给不出真正的保证——
DNS rebinding（校验通过后改解析）是本项目已登记的残留风险，保存时解析对它毫无作用。

保存时仍然能拦住最常见的攻击输入：`http://127.0.0.1/`、`http://169.254.169.254/`
（云元数据服务）、`http://10.x`、`http://[::1]/`、`http://localhost/`、`file://` ——
它们都不需要 DNS 就能判定。冒烟测试里有 9 项覆盖这些。

**这是一次核心改动** 与阶段 5 的复核点无关（不是三轴维度切分问题），而是阶段 6 的测试
暴露出的核心自身缺陷。核心改动本身是修复而非优化，因此直接改。

---

## ADR-025 网页采集"先剔除已入库链接，再抓详情页"

**背景** 网页采集与 RSS 的成本结构完全不同：RSS 一次请求拿到全部条目；网页采集是
列表页 1 次 + 每个条目 1 次。

**决定** 两阶段之间插入一步：用 `external_id`（即 URL）批量比对本源已入库的条目，
把已知链接剔除后再抓详情页。

**效果** 稳定状态下每轮只有 1 次请求（列表页）；列表页新增 N 条时只抓 N 个详情页。
没有这一步的话，每轮都会把列表页上的全部条目重抓一遍——一个每天更新 1 条、列表页显示
30 条的博客，每轮会浪费 29 次请求。

**代价** 传输 component 需要查询 `infohub.item`。这看似越界（传输不该关心去重），但
"不要抓已经有的东西"确实是传输层的效率职责，而且它只读不写。

**验收** 阶段 6 测试第 5 节：第二轮完全不抓详情页；列表页新增一条时只抓那一条。

---

## ADR-026 网页采集用 CSS 选择器配置，而非每站一个模块

**决定** `infohub.web.profile` 模型承载全部站点差异：列表页 URL 模板、条目链接选择器、
分页方式、各字段选择器、噪声剔除选择器。接入结构常规的站点 = 加一条记录。

**否决方案**

* *每个站点一个模块*（各写一个 provider mapper）—— 模块数随站点数线性增长，违背 N10。
  这正是 ADR-018 判定表里"新网站但结构常规 → 建一条配置记录，模块数增加 0"那一行。
* *XPath 而非 CSS* —— XPath 表达力更强，但对配置作者门槛高得多。且 `cssselect` 未安装，
  `lxml.cssselect` 不可用，而 bs4 + soupsieve 容器自带。
* *把选择器写进源记录* —— 多个源共用同一站点结构时要重复填；独立成模型可复用。

**代价** 选择器会随站点改版失效，这是网页采集固有的维护成本。缓解：配置上有「备注」
字段记录结构假设；抓取日志的 `item_found` 为 0 就是失效信号。

**边界** 需要 JS 渲染、登录、反爬对抗的站点仍然要写渠道模块。`render_js` 字段目前只是
预留——勾选后**直接报错**，而不是静默抓到未渲染的空壳页面。


---

## ADR-027 摘要邮件按 (用户, 周期) 分组，用发送记录做幂等

**决定** 一封邮件覆盖该用户该周期的**全部**订阅。到期判定查 `infohub.digest.log`
里"该 (用户, 周期) 在本周期内是否已有成功记录"。

**否决方案**

* *一个订阅一封邮件* —— `digest_frequency` 是订阅级字段，最直白的实现就是逐订阅发。
  但订了 10 个学科的用户会收到 10 封，体验很差。
* *在用户或订阅上放 `last_digest_at` 时间戳* —— 单个时间戳在 cron 重跑、多 worker
  并发、发送中途失败时会漏发或重发。发送记录能给出准确答案，顺带也是运营需要的东西
  （谁在什么时候收到几条、有没有发失败）。

**关键细节：`skipped` 也算已处理。** 本周期没有未读内容时记一条 `skipped`，否则每轮
cron 都要为这个用户重新计算一遍条目。而 `failed` 不算已处理，留给下一轮重试。

**收益** cron 是重跑安全的，一天跑几次都不会重复发。

---

## ADR-028 摘要邮件正文用 QWeb 视图渲染，不用 mail.template

**决定** 渲染 `ir.ui.view`（`infohub_digest.digest_email`）后建 `mail.mail`。

**否决方案** *`mail.template`* —— 模板正文需要遍历"该用户该周期的未读条目"，而
`mail.template` 的渲染上下文只有 `object`（一条 `res.users`），要在模板里拿这套动态
数据得靠调用模型方法，很别扭且难调试。

**可编辑性没有损失** QWeb 视图本身也是数据库记录，管理员照样能改。

**代价** 失去了 `mail.template` 自带的多语言、附件、邮件服务器选择等能力。当前不需要；
真需要时可以把渲染结果塞进一个极简的 `mail.template` body。

---

## ADR-029 LLM 产出写独立字段，不覆盖原文

**决定** `llm_summary` / `llm_translated_title` / `llm_translated_summary` 与
`summary` / `title` 并存。

**理由** 模型会出错、会改口径、会随版本变化。覆盖原文就没法回退、没法对比、没法在换
模型后重新评估质量。前端可以在有 LLM 摘要时优先展示它，但原文始终在库里。

**代价** 多三个字段，前端要决定展示哪个。这个代价远小于丢失原文。

---

## ADR-030 零样本归类必须做事后校验

**决定** 把候选学科编码列进提示、要求只回一个编码，拿到结果后**必须**在候选集里
查得到才采用。查不到就放弃归类，不做任何猜测。

**背景** `llm` 模块没有 JSON mode / `response_format` 的封装。kwargs 虽然能透传到 SDK，
但那是 provider 特有、本仓库未验证的路径，不适合作为正确性的基础。

**为什么校验是必需的而非可选的** 模型返回不存在的编码、多个编码、带解释的整句话都很
常见。测试覆盖了这几种：`"我认为这属于 technology 这个学科"` 能提取出编码；
`"quantum-astrology"` 这种编造的编码被拒绝。**没有事后校验，学科词表会被污染成任意
字符串。**

**候选集限制在 40 个层级浅的学科** 全量 161 个会把提示撑得很长、准确率反而下降。
让模型做粗分，精分留给映射表或人工。

**适用边界** 只在来源**没有**受控分类码时才值得开。arXiv 这类有 `cs.LG` 精确编码的
来源用 `infohub_arxiv` 的映射表 classifier 又准又免费。两者可以共存
（`classifier` 用 `many_components` 取），所以本模块的 classifier 只在源上显式勾了
`llm_classify` 时才匹配。

---

## ADR-031 一次性 LLM 提问的惯用法（本仓库首例）

**背景** 本仓库此前没有任何摘要类的 LLM 调用——唯一的 `chat()` 调用方是
`llm_assistant`，走的是有历史的会话。所以这里建立惯用法。

**决定** 封装在 `infohub_llm/llm_client.py`，做成普通 Python 函数而非 component
（多个 component 都要用，函数比多继承一个抽象 component 更简单也更好测）。

**两个必须记住的 API 反直觉点**

1. `chat(messages, ...)` 的 `messages` 要的是 **`mail.message` 记录集**，不是 dict
   列表。一次性提问传**空记录集** + `prepend_messages`。参照
   `llm.provider._test_chat_model`。
2. **解析失败不抛异常，而是在返回 dict 里给 `error` 键。** 既要 `try/except`，
   又要检查 `response.get("error")`——只做一个会漏掉一半失败。

**统一异常** 所有失败形态（`UserError` / `NotImplementedError` / `ValueError` /
SDK 原生异常 / `error` 键）收敛成 `LlmCallFailed`，调用方只处理一种。

**显式超时** `llm` 模块没有任何超时设置，SDK 默认可能长达数百秒。客户端显式传
`timeout=90`，避免一个卡住的调用把 worker 占满。
