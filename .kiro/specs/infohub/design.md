# InfoHub 设计文档

## 1. 架构总览

### 1.1 模块结构

```
infohub                 核心：源、条目、学科词表、标签、订阅、per-user 状态、
                              审核状态机与人工标黑、HTTP 客户端基类、三轴 component 抽象
├── infohub_rss         RSS/Atom（新闻 + 博客）
├── infohub_web         无 RSS 站点的选择器抓取
├── infohub_fulltext    正文提取，补全只有摘要的条目
├── infohub_paper       论文介质层（DOI/摘要/作者/期刊，只存 URL 不存 PDF）
│   ├── infohub_arxiv       arXiv 采集 + cs/math/physics 学科映射
│   └── infohub_pubmed      （未来）生物医学 + MeSH 映射
├── infohub_social      社交介质层（未来）
│   └── infohub_twitter     X API v2（未来）
├── infohub_filter      规则引擎：自动打标签/评分/屏蔽
├── infohub_website     ★ 前端阅读：时间线、条目页、订阅管理
├── infohub_digest      定期摘要邮件
└── infohub_llm         桥接 llm：摘要、翻译、自动学科分类
```

核心依赖：`base`、`mail`、`component`、`queue_job`。

### 1.2 三条结构性决定

**HTTP 客户端在核心。** `infohub_rss`、`infohub_web`、`infohub_arxiv` 都要出网，而 SSRF 防护、超时、响应体积上限、条件请求本就是核心安全职责（N3/N5），所以核心提供 HTTP 组件基类，不单开传输模块。

**审核状态机与人工标黑在核心，规则引擎在 `infohub_filter`。** portal 的记录规则依赖 `item.state`（R5.1、N7），核心不能依赖一个可选模块。核心的 `_moderate()` 钩子默认直接发布，`infohub_filter` 覆盖它插入规则求值（R6.4）。

**`infohub_arxiv` 同时贡献 transport 与 provider 两个维度。** 这偏离 N9 的理想，原因是 arXiv 的分页与续传语义属于它自己。不预先抽象共用的 API 分页与限流；等 `infohub_pubmed` 落地、确认重复出现后再上提。此偏离已按 N9 要求在此记录。

## 2. 三轴组合模型

信息源不是单继承树上的一个节点，而是三个正交维度的组合（R1.1）：

```
infohub.source = medium × transport × provider
                   介质      传输       来源
```

| 维度 | 决定 | 取值来源 |
|---|---|---|
| `medium` | 条目的字段语义与扩展数据结构、**去重身份的算法** | `article`（核心）、`paper`（`infohub_paper`）、`post`（`infohub_social`） |
| `transport` | 怎么拿到字节、怎么做增量 | `http`（核心）、`rss`、`web`、`arxiv_api` |
| `provider` | 该来源特有的字段映射与分类码 | `generic`（核心默认）、`arxiv`、`pubmed` |

各维度用 `_selection_add` 独立扩展。示例组合：

| 来源 | medium | transport | provider | 需要写代码吗 |
|---|---|---|---|---|
| 某新闻站 RSS | `article` | `rss` | `generic` | 否，建一条源记录 |
| 某博客（无 RSS） | `article` | `web` | `generic` | 否，建一条选择器配置 |
| 期刊新刊 RSS | `paper` | `rss` | `generic` | 否 |
| arXiv | `paper` | `arxiv_api` | `arxiv` | 是，一个渠道模块 |

组合带来的关键收益：论文经 RSS 进来时，RSS 传输逻辑来自 `infohub_rss`、论文字段与 DOI 去重来自 `infohub_paper`，**两者之间没有任何继承关系**，也不需要在论文分支里重写一遍条件请求。

### 2.1 合法组合 = 可解析性

不维护组合白名单（那会有两处需要同步）。改为在约束里尝试解析三个维度对应的 component（R1.2）：

```python
@api.constrains("medium", "transport", "provider")
def _check_composition(self):
    for source in self:
        with source.work_on() as work:
            for usage in ("transport", "medium", "mapper"):
                try:
                    work.component(usage=usage)
                except NoComponentError as exc:
                    raise ValidationError(_(
                        "组合 (%(m)s, %(t)s, %(p)s) 缺少 %(u)s 实现，"
                        "请确认已安装对应模块。",
                        m=source.medium, t=source.transport,
                        p=source.provider, u=usage)) from exc
```

组合的合法性由"有没有人实现"自动定义，装上新模块即自动放开新组合。

### 2.2 预设：把三个维度对管理员藏起来

三个 Selection 对管理员是认知负担。每个渠道模块用 `noupdate="1"` 数据文件带一批预设（R1.3）：

```xml
<record id="preset_arxiv_cs_lg" model="infohub.source.preset">
    <field name="name">arXiv — cs.LG 机器学习</field>
    <field name="medium">paper</field>
    <field name="transport">arxiv_api</field>
    <field name="provider">arxiv</field>
    <field name="endpoint">http://export.arxiv.org/api/query?search_query=cat:cs.LG</field>
    <field name="topic_ids" eval="[(4, ref('infohub_paper.topic_cs_lg'))]"/>
</record>
```

日常"加一个期刊/一个板块"退化为加一条数据记录——这是把模块数量压成次线性（N10）的落点。

## 3. 数据模型

### 3.1 核心

**`infohub.source`** —— 同时是 component 的 collection：

```python
class InfohubSource(models.Model):
    _name = "infohub.source"
    _inherit = ["collection.base", "mail.thread"]     # collection.base 是三轴多态的前提

    name = fields.Char(required=True)
    active = fields.Boolean(default=True)

    # 三轴
    medium = fields.Selection([("article", "文章")], required=True, default="article")
    transport = fields.Selection([("http", "HTTP")], required=True)
    provider = fields.Selection([("generic", "通用")], required=True, default="generic")

    endpoint = fields.Char()                  # URL / API 端点
    credential_id = fields.Many2one("infohub.credential")
    access_level = fields.Selection([("public", "公开"), ("internal", "内部")],
                                    default="public", required=True)

    # 调度
    interval_number = fields.Integer(default=1)
    interval_type = fields.Selection([("minutes", "分钟"), ("hours", "小时"), ("days", "天")],
                                     default="hours")
    next_run_at = fields.Datetime(index=True)
    last_run_at = fields.Datetime(readonly=True)

    cursor_state = fields.Json(readonly=True)  # ETag / since_id / 最后发布时间，形态因源而异 (R2.1)

    error_count = fields.Integer(readonly=True)
    last_error = fields.Text(readonly=True)
    max_errors = fields.Integer(default=10)    # 达到即自停 (R1.6)

    topic_ids = fields.Many2many("infohub.topic")       # 默认学科 (R1.5)
    default_tag_ids = fields.Many2many("infohub.tag")
```

`work_on` 注入源记录，供 `_component_match` 读三个维度：

```python
@contextmanager
def work_on(self, model_name=None, **kwargs):
    self.ensure_one()
    kwargs.setdefault("source", self)
    with super().work_on(model_name or "infohub.item", **kwargs) as work:
        yield work
```

**`infohub.item`** —— 核心条目表，**不含任何 per-user 字段，也不含任何介质特有字段**：

```python
class InfohubItem(models.Model):
    _name = "infohub.item"
    _order = "published_at desc, id desc"

    source_id = fields.Many2one("infohub.source", required=True, index=True, ondelete="cascade")
    medium = fields.Selection(related="source_id.medium", store=True, index=True)

    external_id = fields.Char(index=True)      # 源内身份 (R3.1)
    identity_key = fields.Char(index=True)     # 跨源身份，由介质计算 (R3.2/R3.3)

    title = fields.Char(required=True)
    url = fields.Char()
    author_name = fields.Char()
    summary = fields.Html(sanitize=True)
    content = fields.Html(sanitize=True)       # 会渲染到公开页面，净化是硬要求 (N4)
    content_text = fields.Text()               # 去标签，供全文检索
    lang = fields.Char(index=True)

    published_at = fields.Datetime(index=True)
    fetched_at = fields.Datetime(readonly=True)

    primary_topic_id = fields.Many2one("infohub.topic", index=True)
    topic_ids = fields.Many2many("infohub.topic")
    tag_ids = fields.Many2many("infohub.tag")
    score = fields.Float(default=0.0)

    state = fields.Selection([("fetched", "已抓取"), ("published", "已发布"),
                              ("rejected", "已拒绝"), ("blocked", "已标黑")],
                             default="fetched", required=True, index=True)

    raw_data = fields.Json()                   # 原始报文，供改解析后重跑 (R2.5)

    _unique_external = models.Constraint(
        "UNIQUE(source_id, external_id)", "该源下条目已存在。")
    _identity_idx = models.Index("(identity_key) WHERE identity_key IS NOT NULL")
    _timeline_idx = models.Index("(state, published_at DESC)")   # 时间线主查询 (N1)
```

**`infohub.medium.payload`** —— 介质载荷契约（R2.7）。介质特有字段分表存放，核心表不随介质数量膨胀，卸载介质模块时其表整体消失：

```python
class InfohubMediumPayload(models.AbstractModel):
    _name = "infohub.medium.payload"
    _description = "Medium Payload Mixin"

    item_id = fields.Many2one("infohub.item", required=True, index=True, ondelete="cascade")
    _unique_item = models.Constraint("UNIQUE(item_id)", "每个条目只能有一份介质载荷。")
```

代价是显示介质字段需要 join。缓解手段：把最常用的一两个字段（如 DOI）在 `infohub.item` 上开 `related` 字段。

**`infohub.item.read`** —— per-user 稀疏交互表（R8）：

```python
class InfohubItemRead(models.Model):
    _name = "infohub.item.read"

    user_id = fields.Many2one("res.users", required=True, index=True, ondelete="cascade")
    item_id = fields.Many2one("infohub.item", required=True, index=True, ondelete="cascade")
    is_read = fields.Boolean(default=True)
    read_at = fields.Datetime()
    is_starred = fields.Boolean()
    is_hidden = fields.Boolean()

    _unique_user_item = models.Constraint("UNIQUE(user_id, item_id)", "...")
    _star_idx = models.Index("(user_id) WHERE is_starred")
```

**`infohub.subscription`** —— 也继承 `collection.base`，让订阅维度可插拔（R7.2）：

```python
class InfohubSubscription(models.Model):
    _name = "infohub.subscription"
    _inherit = "collection.base"

    user_id = fields.Many2one("res.users", required=True, index=True,
                              default=lambda self: self.env.user)
    name = fields.Char()
    active = fields.Boolean(default=True)

    target_type = fields.Selection([("source", "信息源"), ("topic", "学科"), ("tag", "标签")],
                                   required=True)
    source_id = fields.Many2one("infohub.source")
    topic_id = fields.Many2one("infohub.topic")
    tag_id = fields.Many2one("infohub.tag")

    medium_filter = fields.Char()        # 可选：只要 paper / 只要 article
    last_read_at = fields.Datetime()     # 未读水位线，见 5.2
    digest_frequency = fields.Selection([("none", "不推送"), ("daily", "每日"), ("weekly", "每周")],
                                        default="none")
```

**`infohub.topic`** —— 层级受控词表（R4.1）。`_parent_store = True` 是 `child_of` 高效查询的前提：

```python
class InfohubTopic(models.Model):
    _name = "infohub.topic"
    _parent_store = True
    _parent_name = "parent_id"
    _order = "complete_name"

    name = fields.Char(required=True, translate=True)
    code = fields.Char(index=True)
    parent_id = fields.Many2one("infohub.topic", ondelete="cascade", index=True)
    parent_path = fields.Char(index=True, unaccent=False)
    complete_name = fields.Char(compute="_compute_complete_name", store=True, recursive=True)
```

**`infohub.topic.mapping`** —— 外部分类码到学科的映射（R4.3、R4.5）。没有这张表，每接一个新学科源都要写死一批 if/elif：

```python
class InfohubTopicMapping(models.Model):
    _name = "infohub.topic.mapping"

    provider = fields.Char(required=True, index=True)        # 'arxiv' / 'pubmed'
    external_code = fields.Char(required=True, index=True)   # 'cs.LG' / MeSH ID
    topic_id = fields.Many2one("infohub.topic", required=True, ondelete="cascade")

    _unique_code = models.Constraint("UNIQUE(provider, external_code)", "...")
```

**`infohub.blocklist`** —— 人工标黑（R5.3–R5.6）：

```python
class InfohubBlocklist(models.Model):
    _name = "infohub.blocklist"

    block_type = fields.Selection([("item", "单条"), ("source", "来源"), ("domain", "域名"),
                                   ("keyword", "关键词"), ("author", "作者")],
                                  required=True)      # _selection_add 可扩展 (R5.6)
    value = fields.Char()                             # domain / keyword / author 用
    item_id = fields.Many2one("infohub.item", ondelete="cascade")
    source_id = fields.Many2one("infohub.source", ondelete="cascade")
    reason = fields.Text()
    user_id = fields.Many2one("res.users", default=lambda self: self.env.user, readonly=True)
    active = fields.Boolean(default=True)
```

两种语义必须分开处理：`item` 级是**回溯的**（把已发布条目立即撤下，R5.3）；`domain`/`keyword`/`author` 级是**前瞻的**（新条目进入时判定，R5.4），并额外提供一次性回溯扫描动作（R5.5）。

**其他核心模型**：`infohub.tag`、`infohub.credential`（凭证隔离，R1.7/N6）、`infohub.source.run`（抓取日志，R2.4）、`infohub.source.preset`（R1.3）。`res.users` 扩展 `infohub_muted_tag_ids`、`infohub_lang_ids`、`infohub_subscription_ids`（R7.3）。

### 3.2 论文介质（`infohub_paper`）

```python
class InfohubPaper(models.Model):
    _name = "infohub.paper"
    _inherit = "infohub.medium.payload"

    doi = fields.Char(index=True)
    doi_normalized = fields.Char(index=True)     # 去重用 (R11.3)
    abstract = fields.Text()
    author_ids = fields.Many2many("infohub.paper.author")
    journal_id = fields.Many2one("infohub.journal")
    volume = fields.Char()
    issue = fields.Char()
    pages = fields.Char()
    published_version = fields.Selection([("preprint", "预印本"), ("accepted", "已接收"),
                                          ("published", "已发表")])
    citation_count = fields.Integer()
    pdf_url = fields.Char()          # 只存 URL，不下载 (R11.2)
```

配套 `infohub.paper.author`、`infohub.journal`（R11.4）。arXiv 学科树作为数据放本模块（R4.4）——它是学科体系的主要消费者，且 `infohub_pubmed` 可复用同一棵树；而 `cs.LG → topic` 的编码映射放 `infohub_arxiv`。**树与映射分开**，接新学科只加映射数据。

## 4. Component 扩展点

三个抽象基类各自只看一个维度，互不继承（N8）：

```python
class TransportBase(AbstractComponent):
    _name = "infohub.transport.base"
    _collection = "infohub.source"
    _usage = "transport"
    _transport = None

    @classmethod
    def _component_match(cls, work, usage=None, model_name=None, **kw):
        return cls._transport == work.source.transport


class MediumBase(AbstractComponent):
    _name = "infohub.medium.base"
    _collection = "infohub.source"
    _usage = "medium"
    _medium = None
    _payload_model = None

    @classmethod
    def _component_match(cls, work, usage=None, model_name=None, **kw):
        return cls._medium == work.source.medium


class MapperBase(AbstractComponent):
    _name = "infohub.mapper.base"
    _collection = "infohub.source"
    _usage = "mapper"
    _provider = None
    _transport = None        # generic mapper 按传输区分

    @classmethod
    def _component_match(cls, work, usage=None, model_name=None, **kw):
        if cls._provider != work.source.provider:
            return False
        return cls._transport is None or cls._transport == work.source.transport
```

**要避开的框架陷阱**：`WorkContext.component()` 匹配到多个会抛 `SeveralComponentError`，而它内置的消歧只按 collection 和 model（见 `component/core.py` 的 `_filter_components_by_collection` / `_filter_components_by_model`），在三轴场景下都帮不上忙。因此 `provider` 必须是**必填且默认 `generic`**，不能留空——这样每个源恰好命中一个 mapper。`infohub_rss` 提供 `(generic, rss)`，`infohub_web` 提供 `(generic, web)`，互不冲突。

其余扩展点：

| usage | 取法 | 匹配维度 | 职责 |
|---|---|---|---|
| `transport` | `component` | transport | 出网、增量游标 |
| `mapper` | `component` | provider + transport | 原始条目 → 归一化 payload |
| `medium` | `component` | medium | 介质字段落库、**计算去重身份** |
| `classifier` | `many_components` | provider / medium | 学科归类（查映射表 / LLM 零样本） |
| `enricher` | `many_components` | 任意 | 正文提取、LLM 摘要 |
| `subscription.matcher` | `component` | target_type | 订阅 → domain |

去重身份归属介质维度是重要结论（R3.3）：同一篇论文经 arXiv、期刊 RSS、Crossref 三条路进来，靠归一化 DOI 收敛为一条；而新闻的身份是 GUID 或规范化 URL。这个差异用介质 component 表达，不散落在各 provider 里。

```python
class PaperMedium(Component):
    _name = "infohub.medium.paper"
    _inherit = "infohub.medium.base"
    _medium = "paper"
    _payload_model = "infohub.paper"

    def identity(self, payload):
        return self._normalize_doi(payload.get("doi")) or payload.get("arxiv_id")
```

## 5. 关键流程

### 5.1 采集流水线

```
cron 调度  →  每源一个 job  →  transport.fetch()   → 原始条目 + 新游标
                              →  mapper.map()       → 归一化 payload
                              →  medium.identity()  → 去重身份
                              →  去重比对           → 落 item + 介质载荷
                              →  classifier(多个)   → 学科
                              →  _moderate()        → published / rejected / blocked
                              →  enricher(多个) 各派独立 job
```

调用方不含任何 `if source_type == ...` 分支：

```python
def _fetch(self):
    self.ensure_one()
    with self.work_on() as work:
        entries, cursor = work.component(usage="transport").fetch()
        mapper = work.component(usage="mapper")
        medium = work.component(usage="medium")
        for entry in entries:
            payload = mapper.map(entry)
            payload["identity_key"] = medium.identity(payload)
            item = self._upsert_item(payload)          # R3.1/R3.2
            if not item:
                continue
            medium.store_payload(item, payload)        # R2.7
            for classifier in work.many_components(usage="classifier"):
                classifier.classify(item, entry)
            item._moderate()                            # R5.2
        self.cursor_state = cursor                      # R2.1
```

### 5.2 时间线与未读（拉取式）

不做扇出。条目只存一份，时间线由订阅动态拼 domain（R7.4/R7.5）：

```python
from odoo.fields import Domain          # Odoo 19：不再用 odoo.osv.expression

def _timeline_domain(self):
    user = self.env.user
    subs = user.infohub_subscription_ids.filtered("active")
    if not subs:
        return Domain.FALSE
    matched = Domain.OR([
        work.component(usage="subscription.matcher").domain(sub)
        for sub in subs
        for work in [sub.work_on("infohub.item").__enter__()]
    ])
    return matched & Domain("state", "=", "published") \
                   & Domain("tag_ids", "not in", user.infohub_muted_tag_ids.ids)
```

（上面为表达紧凑，实际实现中 `work_on` 应以正常的 `with` 块使用，逐个订阅收集 domain 后再合并。）

matcher 示例，`child_of` 让"订阅计算机科学"自动覆盖全部子学科（R4.1）：

```python
class TopicMatcher(Component):
    _name = "infohub.subscription.matcher.topic"
    _collection = "infohub.subscription"
    _usage = "subscription.matcher"
    _target_type = "topic"

    def domain(self, sub):
        return [("topic_ids", "child_of", sub.topic_id.id)]
```

选拉取式的理由：扇出式在 200 用户 × 50 万条目下是 10⁸ 行，且改订阅要回溯重算；拉取式改订阅零成本，加订阅维度只需加一个 matcher。

代价是未读数不能直接 count。解法是每个订阅上的 `last_read_at` 水位线（R8.3）：

> 未读 = 命中 domain 且 `published_at > last_read_at` 且不在已读表中

这样已读表始终稀疏（R8.2），不随时间线性膨胀。

### 5.3 审核

核心的钩子默认放行（R5.2），保证不装 `infohub_filter` 也能工作（R6.4）：

```python
# infohub/models/infohub_item.py
def _moderate(self):
    for item in self:
        if item._check_blocklist():          # 前瞻黑名单 R5.4
            item.state = "blocked"
        else:
            item.state = "published"

# infohub_filter/models/infohub_item.py
def _moderate(self):
    remaining = self.env["infohub.rule"]._apply(self)   # 规则求值 R6.1-R6.3
    return super(InfohubItem, remaining)._moderate()
```

`infohub_filter` 的 `infohub.rule`：`sequence`、`condition_domain`、`keyword_regex`、`action`（publish/reject/tag/score/topic）、`tag_ids`、`score_delta`、`topic_ids`、`stop_after`。

## 6. Website 层与权限

### 6.1 路由（`infohub_website`，依赖 `website`）

| 路由 | auth | 说明 |
|---|---|---|
| `/infohub` | `user` | 个人时间线，按学科/标签/未读筛选与分页（R9.1） |
| `/infohub/item/<int:item_id>` | `user` | 条目详情，打开即写已读（R9.2） |
| `/infohub/subscriptions` | `user` | 订阅管理（R9.3） |
| `/infohub/topic/<model("infohub.topic"):topic>` | `public` | 公开学科浏览页（可选） |

### 6.2 权限模型

| 组 | 类型 | 权限 |
|---|---|---|
| `group_reader` | portal | 读 `state = published` 条目；读写**自己的** `item.read` 与 `subscription`；读 topic/tag |
| `group_user` | 内部 | 后台查看条目、源、抓取日志 |
| `group_moderator` | 内部 | 标黑、改 state、管规则 |
| `group_manager` | 内部 | 管源、凭证、学科词表 |

三个必须做对的点：

1. **`infohub.item` 的记录规则只按 `state` 和 `source_id.access_level` 过滤**，都是索引字段。**不按订阅过滤**——订阅是展示逻辑，放控制器里。按 m2m 订阅做记录规则会在几十万行上退化成慢查询（N1）。这样做在安全上成立，因为这些是公开网页内容，泄露不构成机密问题；`access_level = internal` 的源则对 portal 不可见，为将来接付费源留口。
2. **portal 用户能创建自己的订阅**，所以 `infohub.subscription` 需要 create 权限 + 记录规则 `[('user_id','=',user.id)]`。`infohub.item.read` 同理。漏了记录规则会导致用户可读改他人订阅与阅读状态（N7）。
3. **`infohub.credential` 对 portal 与 `group_user` 完全无权限**（N6）。`infohub.source` 对 portal 只给读，且凭证走独立模型而非源上的字段。

## 7. 异步执行

Channel 声明（`data/queue_data.xml`，遵循仓库既有约定）：

```xml
<odoo noupdate="1">
    <record id="channel_infohub" model="queue.job.channel">
        <field name="name">infohub</field>
        <field name="parent_id" ref="queue_job.channel_root"/>
    </record>
</odoo>
```

一个 `ir.cron` 只做调度：挑出 `next_run_at <= now` 的源，每源派一个 job（R2.2）。`identity_key` 防止慢源在上一轮未完成时被重复入队（R2.3）：

```python
source.with_delay(
    channel="root.infohub",
    description=_("Fetch %s") % source.name,
    identity_key="infohub-fetch-%s" % source.id,
)._fetch()
```

正文提取（R10.2）与 LLM 处理各派独立 job，避免长任务拖住采集。

### 7.1 全局速率限制（R2.8）

来源方的限速是**按来源方**而不是按源记录计的。arXiv 建议约 3 秒一次请求，而实际会存在多个 arXiv 源（cs.LG、cs.CV、math.AP…），它们是独立的 `infohub.source` 记录，`identity_key` 只能保证**同一个源**不并发，无法阻止多个 arXiv 源同时出网并合计超速。

方案：**专用通道容量 1 + 进程内最小间隔**，不自建令牌桶。

1. 声明子通道（`infohub_arxiv/data/queue_data.xml`）：

```xml
<odoo noupdate="1">
    <record id="channel_arxiv" model="queue.job.channel">
        <field name="name">arxiv</field>
        <field name="parent_id" ref="infohub.channel_infohub"/>
    </record>
</odoo>
```

2. 派发时指定该通道，使所有 arXiv 抓取排成一条队列：

```python
source.with_delay(channel="root.infohub.arxiv", identity_key=...)._fetch()
```

3. 在 transport component 内，两次请求之间按源记录上的 `min_request_interval`（默认 3.0 秒）休眠。

**部署依赖（容易漏，必须写进模块 README）**：通道容量不是数据库字段，而是 odoo.conf 配置。缺这一行则容量沿用默认，限速失效：

```ini
[queue_job]
channels = root:4,root.infohub.arxiv:1
```

或环境变量 `ODOO_QUEUE_JOB_CHANNELS=root:4,root.infohub.arxiv:1`。

为什么不用 DB 令牌桶或 `pg_advisory_lock`：容量 1 的通道已经把并发降为 1，此时"最小间隔"退化为单线程内的 sleep，正确性不依赖分布式协调。令牌桶只有在需要"并发 N 且总速率受限"时才有必要，arXiv 不属于这种情形。代价是 arXiv 抓取整体串行——但在 3 秒/请求的约束下，它本来就无法并行。

同一模式可复用于将来任何有限速要求的来源方：加一个子通道 + 一行配置。

## 8. Portal 自助注册（R9.5/R9.6）

`infohub_website` 依赖 `auth_signup`，开放自助注册并要求邮箱验证。配套措施：

- 新注册用户自动加入 `infohub.group_reader`（通过 `res.config.settings` 的默认门户组，或注册后钩子）。
- **默认订阅**：注册完成后按一组标记为"推荐"的学科/源自动建立订阅，避免首次进入时间线为空（R9.6）。
- 注册滥用的基本防护：邮箱验证必过、注册频率限制、可选的邀请码开关（留字段不实现）。
- 注册用户是 portal 用户，其权限完全由 §6.2 的记录规则约束；自助注册不放宽任何数据可见性。

## 9. 安全设计

| 风险 | 措施 | 落点 |
|---|---|---|
| SSRF（N3） | 限制 scheme 为 http/https；解析域名后拦截私有网段、环回、链路本地地址；限制重定向跳数并对每跳复检 | `infohub.source` 的 constraint + 核心 HTTP 组件基类 |
| XSS（N4） | `fields.Html(sanitize=True)`，并剥离 `<script>`/`<iframe>`/`on*`；QWeb 模板中**一律用 `t-out`，禁止 `t-raw`**；正文将渲染到公开页面，风险高于后台 | `infohub.item.content` / `summary`、`infohub_website` 模板 |
| 资源耗尽（N5） | 连接与读取超时、响应体积上限、条目数上限 | 核心 HTTP 组件基类 |
| 凭证泄露（N6） | 独立 `infohub.credential` 模型，仅 `group_manager` 可读 | security ACL |
| 越权读写（N7） | 订阅与阅读状态的记录规则限定 `user_id = user.id` | security 记录规则 |

## 10. 复核点

第 5 阶段（`infohub_paper` + `infohub_arxiv`）是三轴抽象的真正考验：**如果接入 arXiv 需要修改 `infohub` 核心，说明维度切分错了。** 届时返工的成本远低于后期。

目前无未决设计问题。设计取舍的完整记录（含被否决方案与理由）见 `decisions.md`；当前进度与交接状态见 `progress.md`。
