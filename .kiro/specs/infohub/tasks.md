# InfoHub 实施任务

约定：Odoo 19、LGPL-3、版本号 `19.0.1.0.0`、author `quick-sort@outlook.com`。Python 依赖走 `__manifest__.py` 的 `external_dependencies`。SQL 约束用 `models.Constraint`，复合索引用 `models.Index`，列表视图用 `<list>`。

---

## 阶段 1 — `infohub` 核心

- [x] 1.1 模块骨架：`__manifest__.py`（依赖 `base`、`mail`、`component`、`queue_job`）、目录 `models/ components/ views/ security/ data/`
- [x] 1.2 `infohub.source`：继承 `collection.base` + `mail.thread`，三轴字段、调度字段、`cursor_state`、错误计数与自停 — R1.1/R1.4/R1.5/R1.6/R2.1
- [x] 1.3 `infohub.source` 覆盖 `work_on()` 注入 `source`，实现 `_check_composition()` 可解析性约束 — R1.2
- [x] 1.4 `infohub.credential` + ACL 隔离 — R1.7/N6
- [x] 1.5 `infohub.source.preset` 模型与"由预设建源"动作 — R1.3
- [x] 1.6 `infohub.item`：核心字段、`state`、`identity_key`、`raw_data`、唯一约束与时间线索引 — R2.6/R3.1/R2.5/N1
- [x] 1.7 `infohub.medium.payload` 抽象契约 — R2.7
- [x] 1.8 `infohub.topic`（`_parent_store`）、`infohub.topic.mapping`、`infohub.tag` — R4.1/R4.2/R4.3
- [x] 1.9 `infohub.subscription`（继承 `collection.base`）+ 三个内置 matcher component — R7.1/R7.2
- [x] 1.10 `res.users` 扩展：屏蔽标签、关注语言、订阅 o2m — R7.3
- [x] 1.11 `infohub.item.read` 稀疏交互表 + 索引 — R8.1/R8.2
- [x] 1.12 时间线 domain 构建 `_timeline_domain()` 与按订阅的未读计数（水位线） — R7.4/R7.5/R8.3
- [x] 1.13 三轴 component 抽象基类：`transport.base` / `medium.base` / `mapper.base`，各自 `_component_match` — N8
- [x] 1.14 `article` 介质 component（默认介质，身份 = GUID 或规范化 URL） — R3.3
- [x] 1.15 HTTP 客户端组件基类：超时、体积上限、重定向复检、**SSRF 防护**、条件请求 — N3/N5
- [x] 1.16 采集流水线编排 `_fetch()`：transport → mapper → medium → 去重 → classifier → `_moderate` → enricher — R2.x/R3.x
- [x] 1.17 `infohub.source.run` 抓取日志 — R2.4
- [x] 1.18 `queue.job.channel` 声明 `root.infohub` + 调度 cron + `identity_key` 防重入队 — R2.2/R2.3
- [x] 1.19 审核状态机与 `_moderate()` 钩子（默认发布） — R5.1/R5.2
- [x] 1.20 `infohub.blocklist`：item 级回溯撤下、domain/keyword/author 级前瞻拦截、一次性回溯扫描动作 — R5.3/R5.4/R5.5/R5.6
- [x] 1.21 四个权限组 + ACL + 记录规则（item 按 `state`/`access_level`；subscription 与 item.read 限本人） — N7
- [x] 1.22 后台视图：源（list/form/kanban）、条目（list/form/search，含学科与标签筛选）、学科树、标签、黑名单、抓取日志 — R9.4
- [x] 1.23 顶层学科根节点种子数据
- [x] 1.24 核心通用 `http` 传输（安装验证时补：原本声明了 `transport='http'` 却无实现，按默认值建不出源）

## 阶段 2 — `infohub_rss`

- [x] 2.1 模块骨架，`external_dependencies` 声明 `feedparser`
- [x] 2.2 `transport = rss` component：条件请求（ETag / If-Modified-Since）、编码嗅探、容错解析 — R2.1
- [x] 2.3 `(provider=generic, transport=rss)` mapper：标题/链接/作者/摘要/正文/发布时间/语言，HTML 净化 — R2.6/N4
- [x] 2.4 RSS `<category>` 的宽松学科归类 classifier — R4.3
- [x] 2.5 若干新闻与博客源预设数据 — R12.1
- [x] 2.6 **验收**：新增一个常规 RSS 源不写任何代码 — R12.1（实网测试用预设建源直接抓到 30 条）
- [x] 2.7 英文分类名到学科的 `infohub.topic.mapping` 种子数据（冒烟测试时补：classifier 原本匹配不上中文学科名）
- [x] 2.8 容器安装 + 49 项冒烟测试 + 实网抓取验证

### 阶段 1–2 的验证入口

```bash
# 安装 / 升级
docker exec odoo odoo -c /etc/odoo/odoo.conf -d test_infohub \
    -i infohub,infohub_rss --stop-after-init --workers=0 --no-http

# 冒烟测试（49 项，可重复运行）
docker exec -i odoo odoo shell -c /etc/odoo/odoo.conf -d test_infohub \
    --no-http --workers=0 < .kiro/specs/infohub/smoke_test.py

# 静态引用校验（不需容器）
python3 .kiro/specs/infohub/check_refs.py
```

## 阶段 3 — `infohub_website`（多人订阅阅读闭环）

- [x] 3.1 模块骨架，依赖 `website`
- [x] 3.2 `/infohub` 时间线控制器：订阅 domain + 筛选 + 分页 — R9.1
- [x] 3.3 `/infohub/item/<id>` 详情页，打开写已读 — R9.2
- [x] 3.4 `/infohub/subscriptions` 订阅管理（增删源/学科/标签订阅、屏蔽标签、语言） — R9.3/R7.1/R7.3
- [x] 3.5 收藏与隐藏交互端点
- [x] 3.6 QWeb 模板与 portal 布局集成（正文渲染一律 `t-out`，禁止 `t-raw`） — N4
- [x] 3.7 **安全验收**：以 portal 用户实测无法读写他人订阅与阅读状态、无法看到 `access_level = internal` 的源与非 `published` 条目、无法访问凭证 — N6/N7
- [x] 3.8 依赖 `auth_signup` 开放自助注册 + 邮箱验证；新用户自动入 `group_reader` — R9.5/ADR-011
- [x] 3.9 注册后按"推荐"学科/源建立默认订阅，避免首屏时间线为空 — R9.6
- [x] 3.10 注册滥用防护：按 IP 滑动窗口限流（自清理，不需 cron）
- [x] 3.11 公开学科浏览页 `/infohub/topic/<id>`
- [x] 3.12 54 项 HTTP 端到端测试全通过（`http_test.py`）

> 邮箱验证**未**做成准入门槛：Odoo 自助注册立即创建账号、只发确认邮件。
> 更强的抗滥用应叠加 `auth_signup_uninvited=b2b`、nginx 层限流、或 reCAPTCHA
> （`/web/signup` 在 Odoo 19 已内置 `captcha='signup'` 挂载点）。

## 阶段 4 — `infohub_fulltext` + `infohub_filter`

- [x] 4.1 `infohub_fulltext` 骨架，声明正文提取库依赖
- [x] 4.2 enricher component：按需抓原文、提取正文主体、净化后回写 — R10.1
- [x] 4.3 独立 job 派发，不阻塞采集 — R10.2
- [x] 4.4 `infohub_filter` 骨架
- [x] 4.5 `infohub.rule` 模型：顺序、domain 条件、正则条件、动作、`stop_after` — R6.1/R6.2/R6.3
- [x] 4.6 覆盖 `_moderate()` 插入规则求值 — R6.4
- [x] 4.7 **验收**：卸载 `infohub_filter` 后核心仍能自动发布 — R6.4
      （真做了一次 `button_immediate_uninstall`：模型与表消失，核心审核/标黑/三轴解析全部照常，7 项自检通过；随后重装并全量回归）
- [x] 4.8 规则试运行与「查看命中的条目」（写规则时先验证再启用）
- [x] 4.9 57 项测试全通过（`stage4_test.py`）

## 阶段 5 — `infohub_paper` + `infohub_arxiv`（抽象复核点）

- [x] 5.1 `infohub_paper` 骨架，依赖 `infohub`
- [x] 5.2 `infohub.paper` 载荷表（继承 `infohub.medium.payload`），只存 `pdf_url` — R11.1/R11.2
- [x] 5.3 `infohub.paper.author`、`infohub.journal` — R11.4
- [x] 5.4 `medium = paper` component：DOI 归一化、身份计算、载荷落库 — R3.3/R11.3
- [x] 5.5 arXiv 分类体系导入为学科树种子数据 — R4.4
- [x] 5.6 论文相关后台视图与筛选
- [x] 5.7 `infohub_arxiv` 骨架，依赖 `infohub_paper`
- [x] 5.8 `transport = arxiv_api` component：分页、续传
- [x] 5.9 **全局限速**：声明 `root.infohub.arxiv` 子通道并派发到该通道；transport 内按 `min_request_interval`（默认 3.0s）休眠；**在 README 写明 odoo.conf 需配 `[queue_job] channels = root:4,root.infohub.arxiv:1`** — R2.8/ADR-012
- [x] 5.10 `provider = arxiv` mapper + `cs.LG → topic` 映射数据 + classifier — R12.3
- [x] 5.11 arXiv 板块预设数据
- [x] 5.12 **抽象复核：通过**。整个阶段 5 未修改核心一行代码（实证：`infohub/` 最后修改 11:28，
      阶段 5 起始 23:03）。结论与三处被验证有效的设计见 ADR-021；发现一处设计气味见 ADR-022 — N8/design §10
- [x] 5.13 **验收**：同一篇论文经 arXiv 与期刊 RSS 两路进入，收敛为一条 — R3.2
- [x] 5.14 **限速验收**：通道路由 + 子通道层级 + odoo.conf 容量配置断言（已补 `root.infohub.arxiv:1` 到 odoo.conf）— R2.8
- [x] 5.15 101 项测试全通过（`stage5_test.py`），含 5.13 跨源收敛与反证
- [x] 5.16 两个模块的 README.rst

## 阶段 6 — `infohub_web`

- [x] 6.1 模块骨架，声明 HTML 解析库依赖
- [x] 6.2 `infohub.web.profile` 选择器配置模型：列表页 URL 模板、条目链接选择器、分页方式、详情页各字段选择器、噪声节点剔除、`render_js` 预留
- [x] 6.3 `transport = web` component：两阶段抓取（列表页 → 详情页）、分页、SSRF 与体积约束复用核心基类 — N3/N5
- [x] 6.4 `(provider=generic, transport=web)` mapper
- [x] 6.5 若干博客与期刊站选择器配置数据
- [x] 6.6 **验收通过**：零代码接入新站点（含中文日期自定义格式），全程未安装任何模块 — R12.2/N10
- [x] 6.7 只抓新链接：第二轮完全不抓详情页；列表页新增一条时只抓那一条（ADR-025）
- [x] 6.8 与论文介质组合：`web + paper` 的 DOI 收敛（零代码）
- [x] 6.9 `render_js` 明确报错而非静默抓空
- [x] 6.10 56 项测试全通过（`stage6_test.py`）
- [x] 6.11 **核心修复**：SSRF 校验拆成保存时快速校验 + 请求时完整校验（ADR-024）

## 阶段 7 — 分发与增强

- [x] 7.1 `infohub_digest`：按订阅周期生成并推送摘要邮件 — R13.1（**不做站内通知**，ADR-013）
- [x] 7.2 `infohub_llm`：桥接 `llm`，提供摘要、翻译、零样本学科分类 classifier/enricher — R13.2
- [x] 7.3 `llm_client.py` 建立一次性提问惯用法（本仓库首例，ADR-031）
- [x] 7.4 成本闸门：按源开关默认全关、状态去重、批量上限、输入截断、短文不摘要
- [x] 7.5 零样本归类的事后校验（ADR-030）
- [x] 7.6 摘要邮件幂等（发送记录而非时间戳，ADR-027）+ cron 重跑安全
- [x] 7.7 70 项测试全通过（`stage7_test.py`），LLM 调用全部 mock 不产生费用
- [x] 7.8 两个模块的 README.rst

## 未来

- [ ] `infohub_social` 介质层 + `infohub_twitter`（X API v2，访问权限确认后启动） — R12.5
- [ ] `infohub_pubmed`：MeSH 映射；届时评估是否把 API 分页与限流从 `infohub_arxiv` 上提为共用基类 — R12.4/design §1.2

---

## 里程碑

| 里程碑 | 完成阶段 | 累计模块 | 能力 |
|---|---|---|---|
| M1 采集可用 | 1–2 | 2 | 后台管理源，新闻与博客全量接入 |
| M2 阅读闭环 | 3 | 3 | **多人订阅 + portal 端阅读可用** |
| M3 内容质量 | 4 | 5 | 正文完整、规则过滤与人工标黑齐备 |
| M4 学术接入 | 5 | 7 | 论文与学科体系，三轴抽象通过验证 |
| M5 全渠道 | 6–7 | 10 | 无 RSS 站点、摘要推送、LLM 增强 |
