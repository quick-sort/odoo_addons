# InfoHub 进度与交接状态

> 每次工作结束时更新本文件。会话中断后，从"下一步"接续。

**最后更新** 2026-08-30
**当前状态** **全部 7 个阶段完成。** 10 个模块已在容器实例上安装，通过 **392 项测试**（54 后端 + 54 前端 HTTP + 57 阶段四 + 101 阶段五 + 56 阶段六 + 70 阶段七）+ 实网抓取 + 真卸载验证。**M1–M5 全部里程碑达成；三轴抽象复核通过。**

原计划的所有排期内容已交付。剩余工作见「开放风险」与「未排期」两节。

## ★ 阶段 5 抽象复核结论（design.md §10 的检验）

**通过。整个阶段 5 未修改 `infohub` 核心一行代码。**

实证：`infohub/` 下最后修改的文件时间戳 11:28，而 `infohub_paper/` 与 `infohub_arxiv/`
最早文件 23:03。各模块严格只贡献自己那一轴（paper 贡献 medium；arxiv 贡献
transport + provider）。

被验证有效的设计（详见 ADR-021）：
1. 去重身份归介质轴（ADR-006）—— 期刊 RSS 源只要把介质设成 paper 就能与 arXiv 源按
   DOI 收敛，而 `infohub_rss` 的通用 mapper 完全不知道 DOI 是什么，一行没改
2. 载荷表分离（ADR-005）—— mapper 不需要知道载荷表长什么样
3. `provider` 必填默认 generic（ADR-007）—— 匹配键天然不撞

发现一处设计气味（ADR-022，**暂不改核心**）：`_queue_channel()` 未委托给 transport
component，导致渠道模块要写一个 `if self.transport == ...` 守卫。触发复审的条件是出现
第二个需要专用通道的来源方。

## 测试环境

容器 `odoo`（镜像 `odoo:19.0`），`~/workspace/odoo-projects` 挂载到 `/mnt/extra-addons`，
addons_path 含 `/mnt/extra-addons/odoo_addons`。测试库 `test_infohub`（独立库，不碰现有 `odoo` 库）。

```bash
# 安装 / 升级
docker exec odoo odoo -c /etc/odoo/odoo.conf -d test_infohub \
    -i infohub,infohub_rss,infohub_website,infohub_fulltext,infohub_filter,\
       infohub_paper,infohub_arxiv,infohub_web,infohub_digest,infohub_llm \
    --stop-after-init --workers=0 --no-http

# 四套 shell 测试（可重复运行，各自带首尾清理）
for t in smoke_test stage4_test stage5_test stage6_test stage7_test; do
  docker exec -i odoo odoo shell -c /etc/odoo/odoo.conf -d test_infohub \
      --no-http --workers=0 < .kiro/specs/infohub/$t.py
done

# 前端 HTTP 测试（54 项）——需要先起临时 HTTP 服务
docker exec -d odoo sh -c "odoo -c /etc/odoo/odoo.conf -d test_infohub \
    --http-port=8099 --gevent-port=8098 --db-filter='^test_infohub\$' \
    --workers=0 --max-cron-threads=0 --log-level=error > /tmp/odoo_test_server.log 2>&1"
sleep 30
docker exec -i odoo odoo shell -c /etc/odoo/odoo.conf -d test_infohub \
    --no-http --workers=0 < .kiro/specs/infohub/http_test.py
docker exec odoo pkill -f "http-port=8099"

# 静态引用校验（不需要容器）
python3 .kiro/specs/infohub/check_refs.py
```

**依赖**：`feedparser` 是手工 `pip3 install --break-system-packages feedparser` 装的，
**容器重建会失效**（`infohub_rss` 与 `infohub_arxiv` 都依赖）。`trafilatura` 镜像自带
2.2.0，无需安装。

**odoo.conf 已改**：`[queue_job] channels` 补上了 `root.infohub:2,root.infohub.arxiv:1`
（arXiv 限速依赖它，漏配会静默失效）。**常驻容器需重启才生效**，我没有擅自重启。

常驻容器服务的是 `odoo` 库，而 `odoo shell` 自身不启 HTTP 服务，所以前端测试必须另起
一个 `--db-filter` 限定到测试库的临时服务。

---

## 已完成

### 设计
- [x] 需求梳理 → `requirements.md`（R1–R13、N1–N10、范围外、已决决策）
- [x] 架构设计 → `design.md`（三轴组合、数据模型、component 扩展点、流水线、权限、异步、安全）
- [x] 决策记录 → `decisions.md`（ADR-001 ~ ADR-020，含被否决方案）
- [x] 任务分解 → `tasks.md`（7 阶段，5 个里程碑）
- [x] 开发约束 steering → `.kiro/steering/infohub.md`（编辑 `infohub*` 时自动加载）

### 阶段 1 — `infohub` 核心（约 2900 行 Python + 1450 行 XML）
- [x] 1.1 模块骨架与 manifest
- [x] 1.2–1.5 `infohub.source`（三轴、调度、游标、错误自停）、可解析性约束、`infohub.credential`、`infohub.source.preset`
- [x] 1.6–1.7 `infohub.item`、`infohub.medium.payload` 抽象契约
- [x] 1.8 `infohub.topic`（`_parent_store`）、`infohub.topic.mapping`、`infohub.tag`
- [x] 1.9–1.12 `infohub.subscription` + 3 个 matcher、`res.users` 扩展、`infohub.item.read`、时间线 domain 与未读计数
- [x] 1.13–1.15 三轴 component 抽象基类、`article` 介质、HTTP 基类含 SSRF 防护
- [x] 1.16–1.18 采集流水线 `_fetch`、`infohub.source.run`、`root.infohub` 通道 + 调度 cron
- [x] 1.19–1.20 审核状态机 `_moderate`、`infohub.blocklist`（前瞻拦截 + 回溯扫描）
- [x] 1.21 四个权限组、ACL、记录规则
- [x] 1.22–1.23 后台视图与菜单、学科根节点种子数据
- [x] README.rst（含 odoo.conf 通道容量配置说明）
- [x] 核心 `http` 通用传输（安装验证时发现：原本声明了 `transport='http'` 却没实现，
      导致按默认值根本建不出源）

### 阶段 2 — `infohub_rss`
- [x] 2.1 模块骨架，`external_dependencies` 声明 `feedparser`
- [x] 2.2 `transport = rss`：条件请求（ETag / Last-Modified）+ `last_published` 兜底增量
- [x] 2.3 `(generic, rss)` mapper：字段映射 + HTML 净化 + 原始报文安全序列化
- [x] 2.4 classifier：`<category>` 经映射表归类到学科
- [x] 2.5 源预设数据（通用 RSS、Hacker News、Google Research 博客）+ 15 条英文分类映射
- [x] 2.6 **验收通过**：新增常规 RSS 源零代码——实网测试用预设建源直接抓到 30 条

### 阶段 4 — `infohub_fulltext` + `infohub_filter`
- [x] `infohub_fulltext`：enricher component、候选筛选（三条件）、trafilatura 提取 HTML、净化回写
- [x] 失败分支全覆盖（SSRF / 网络错误 / 未识别正文 / 付费墙式过短），失败后不重试 + 手工重试
- [x] 批量上限 50 条 + 按 `min_request_interval` 休眠，避免打崩来源站
- [x] `infohub_filter`：`infohub.rule` 模型，domain + 正则双条件，五种动作，终结型/标注型区分，`stop_after`
- [x] 保存期校验（坏正则、坏 domain、动作缺配置）+ 试运行与「查看命中的条目」
- [x] 覆盖 `_moderate()` 插入规则求值，`super(InfohubItem, remaining)` 只对未终结子集调用父实现
- [x] **R6.4 硬约束真验证**：`button_immediate_uninstall` 卸载 `infohub_filter` 后，模型与表消失，
      核心的默认发布、人工标黑、三轴解析全部照常（7 项自检通过），随后重装并全量回归
- [x] 两个模块的 README.rst

### 阶段 5 — `infohub_paper` + `infohub_arxiv`（抽象复核点）
- [x] `infohub_paper`：`infohub.paper` 载荷表、`infohub.paper.author`、`infohub.journal`
- [x] `medium = paper` component：DOI/arXiv ID 归一化、身份计算（含从自由文本捞 DOI）、载荷落库
- [x] arXiv 分类体系 161 个学科节点作为树种子（挂在 `infohub.topic_academic` 下）
- [x] 论文独立视图与菜单（放弃 design.md 的 related 方案，理由见模块 README）
- [x] `infohub_arxiv`：`arxiv_api` 传输（分页 + 水位线增量）、`arxiv` mapper、classifier
- [x] 161 条 arXiv 分类码映射 + 7 个板块预设
- [x] 限速：`root.infohub.arxiv` 子通道 + 请求间隔 + **已补 odoo.conf 的 `root.infohub.arxiv:1`**
- [x] **5.13 跨源收敛验收通过**：同一篇论文经 arXiv API 与期刊 RSS 两路进入收敛为一条，
      且有反证（不同 DOI 正常入库，去重没过度合并）
- [x] **5.12 抽象复核通过**：未改核心一行（见上方结论与 ADR-021 / ADR-022）
- [x] 两个模块的 README.rst

### 阶段 6 — `infohub_web`
- [x] `infohub.web.profile` 选择器配置模型（CSS 选择器 + 保存期编译校验）
- [x] `transport = web` 两阶段抓取：列表页翻页 → 剔除已入库链接 → 抓详情页
- [x] 三种分页方式（不分页 / 页码参数 / 下一页链接）+ `list_only` 模式
- [x] `(generic, web)` mapper：噪声剔除 → 字段提取 → 净化；日期支持 datetime 属性与自定义格式
- [x] `same_host_only` 同域限制；详情页链接逐个过 SSRF 校验
- [x] 三份示例配置（纯数据，无代码支撑）+ 两个源预设
- [x] **6.6 验收通过**：零代码接入新站点，含中文日期自定义格式
- [x] **ADR-025 验收**：第二轮完全不抓详情页；新增一条时只抓那一条
- [x] `web + paper` 组合的 DOI 收敛（零代码）
- [x] **核心修复**：SSRF 校验拆两级（ADR-024）
- [x] README.rst

### 阶段 7 — `infohub_digest` + `infohub_llm`
- [x] `infohub.digest.log` 幂等机制（发送记录而非时间戳），三种状态语义
- [x] 按 (用户, 周期) 分组发送，内容筛选六维度（订阅周期/未读/隐藏/屏蔽标签/语言/access_level）
- [x] QWeb 视图渲染邮件正文（内联样式），cron 重跑安全
- [x] `llm_client.py` 建立一次性提问惯用法（空 `mail.message` 记录集 + `prepend_messages`）
- [x] 失败形态统一收敛成 `LlmCallFailed`，显式超时
- [x] enricher：摘要 + 翻译（只译标题与摘要），产出写独立字段不覆盖原文
- [x] classifier：零样本归类 + **事后校验**（编造的编码被拒绝）
- [x] 成本闸门：按源开关默认全关、状态去重、批量上限、输入截断、短文不摘要
- [x] 两个模块的 README.rst

### 验证
- [x] 容器实例安装全部 10 个模块 + `-u all` 全量升级，infohub 相关无 error 无 warning
- [x] 后端冒烟 54 项（`smoke_test.py`）
- [x] 前端 HTTP 端到端 54 项（`http_test.py`）
- [x] 阶段四 57 项（`stage4_test.py`）
- [x] 阶段五 101 项（`stage5_test.py`）
- [x] 阶段六 56 项（`stage6_test.py`）
- [x] 阶段七 70 项（`stage7_test.py`，LLM 全部 mock 不产生费用）
- [x] 实网抓取验证（Hacker News RSS，30 条，第二轮增量 0 条无重复）
- [x] 真卸载/重装验证（`infohub_filter`）
- [x] 静态引用校验（`check_refs.py`，支持多模块与 `_inherit` 链，做过反向验证）

### 阶段 3 — `infohub_website`
- [x] 3.1 模块骨架，依赖 `infohub` / `website` / `portal` / `auth_signup`
- [x] 3.2 `/infohub` 时间线：订阅 domain + 排序/筛选/搜索 + 学科与来源钻取 + 分页
- [x] 3.3 `/infohub/item/<id>` 详情页，打开写已读，上一条/下一条
- [x] 3.4 `/infohub/subscriptions` 订阅管理（增删、摘要频率、屏蔽标签、语言偏好）
- [x] 3.5 收藏/隐藏/已读切换的 jsonrpc 端点
- [x] 3.6 QWeb 模板 + portal 布局集成（`/my` 首页卡片、面包屑），一律 `t-out`
- [x] 3.7 安全验收：越权、CSRF、未发布条目、internal 源全部实测拦住
- [x] 3.8 `auth_signup` 自助注册，新用户自动入 `group_reader`
- [x] 3.9 注册后按「推荐」学科/源建立默认订阅
- [x] 3.10 注册限流（按 IP 滑动窗口，自清理不需 cron）
- [x] 3.11 公开学科浏览页 `/infohub/topic/<id>`
- [x] README.rst（含实现坑位与抗滥用说明）

## 下一步

**排期内的工作已全部完成。** 接下来的候选，按我判断的优先级：

1. **在真实环境上跑一轮**——建几个真实源（RSS + arXiv），观察一周，看抓取稳定性、
   去重效果、正文提取质量。这是当前最大的未知，所有测试都是注入响应。
2. **验证 queue_job 的实际派发**——六套测试都直接调 `_fetch()`，绕过了 `with_delay`。
   `identity_key` 防重入队、通道容量限速的真实效果都还没实测。
3. **决定测试是否转成 Odoo 原生 `tests/`**——六个脚本都是 shell 驱动，不进 CI。
4. **补 `feedparser` 的持久化**（Dockerfile 或 requirements.txt）。
5. 未排期的 `infohub_social` / `infohub_twitter` / `infohub_pubmed`。

## 阶段状态

| 阶段 | 模块 | 状态 |
|---|---|---|
| 1 | `infohub` 核心 | **完成，已验证** |
| 2 | `infohub_rss` | **完成，已验证** |
| 3 | `infohub_website` | **完成，已验证（M2 达成）** |
| 4 | `infohub_fulltext` + `infohub_filter` | **完成，已验证（M3 达成）** |
| 5 | `infohub_paper` + `infohub_arxiv` | **完成，已验证（M4 达成；抽象复核通过）** |
| 6 | `infohub_web` | **完成，已验证** |
| 7 | `infohub_digest` + `infohub_llm` | **完成，已验证（M5 达成）** |
| 未来 | `infohub_social` / `infohub_twitter` / `infohub_pubmed` | 不排期 |

## 实施与验证中发现并修正的缺陷

这几个都是设计文档里没写错、但实现或安装验证时才暴露的问题，记下来避免重犯：

### 写代码阶段发现

1. **component 的继承必须用 `_inherit` 字符串，Python 类继承不算数。**
   最初把三轴基类写成 `class TransportBase(InfohubBase)`。属性能通过 Python MRO
   取到，看起来能用，但 `component/core.py` 的 `_build_component` 只按 `_inherit`
   建立注册表关系——注册表链是断的，第三方模块 `_inherit = "infohub.base"` 追加的
   方法不会被子类继承。已全部改为 `class X(AbstractComponent)` + `_inherit = "..."`，
   与仓库 `connector/components/` 的写法一致。

2. **失败簿记会被 queue_job 的回滚吞掉。**
   抓取失败时 queue_job 回滚整个事务，原本写在主事务里的 `error_count += 1` 随之
   消失，计数永远停在 0，R1.6 的自动停用形同虚设。已改为在 `self.pool.cursor()`
   开的独立 cursor 里写失败计数与失败日志。冒烟测试第 7 节专门验证了"回滚后簿记
   仍存活"。相应地抓取日志改为在结束时才创建（`running` 状态在实践中看不到，
   未提交的行对其他事务不可见，起不到监控作用）。

3. **未读计算原本会物化全部已读 ID。** `id not in [几万个 ID]` 既慢又撑大 SQL。
   已改用 `Domain("read_ids", "not any", [...])` 生成 NOT EXISTS 子查询。

4. **翻译字段上不能加 UNIQUE。** Odoo 19 的 `translate=True` 字段存为 jsonb，
   `UNIQUE(name)` 会退化成比较整个 JSON。`infohub.tag.name` 已去掉 `translate`。

5. **按域名标黑不能用 `url ilike '%cnn.com%'`**，会误伤 `notcnn.com.evil.org`。
   已在 `infohub.item` 上物化 `url_host` 做精确主机名与子域名匹配。

### 安装验证阶段发现

6. **Odoo 19 的 `<group>` 不再接受 `expand` 与 `string` 属性**（见
   `odoo/addons/base/rng/common.rng:294`），会导致视图 RNG 校验失败、模块装不上。
   search 视图里的分组要写成 `<group name="group_by">`。6 个视图全部改正。

7. **翻译字段只支持 trigram 索引**：`index=True` 会被忽略并告警，改成
   `index="trigram"`。另外 `parent_path` 上的 `unaccent` 不是合法字段参数。

8. **核心声明了 `transport = 'http'` 却没有实现**，而 `provider = 'generic'` 也
   没有配套 mapper——按默认值根本建不出任何源，可解析性约束会全部拒绝。已补上核心
   的通用 HTTP 传输实现，并去掉 `transport` 的默认值（避免暗示一个不可用的组合）。

### 冒烟测试阶段发现

9. **游标不能用来向 mapper 传数据。** RSS 传输原本把频道级语言塞进
   `cursor_state`，但游标是整轮结束后才写回 source 的，mapper 在循环里读到的还是
   上一轮的旧游标，第一轮永远读不到。已改用 WorkContext 传递（`self.work.feed_meta`）
   ——这本就是 WorkContext 的设计用途。

10. **无 `@api.depends` 的计算字段不会失效。** `unread_count` 缺 depends，写了
    水位线之后读到的仍是缓存的旧值。已声明订阅自身字段的依赖。

11. **classifier 开箱即废。** RSS 的 `<category>Technology</category>` 匹配不上
    中文学科名「科技」。已在 `infohub_rss` 里补 15 条英文分类名到核心学科的
    `infohub.topic.mapping` 种子数据——这正是映射表要解决的问题，也验证了
    "接新学科只加数据不改代码"（R4.5）确实成立。

12. **冗余索引。** `identity_key` 与 `state` 上的 `index=True` 分别被部分索引
    `identity_idx` 和复合索引 `timeline_idx` 覆盖，已去掉以减少写放大。

### 阶段 3（前端）HTTP 测试阶段发现

13. **公开页不能用 `<model(...)>` 路由转换器。** 该转换器以**当前用户身份** browse
    记录，而匿名访客是 `base.public_user`，我们没给 `base.group_public` 任何 ACL，
    转换器直接失败成 404（三项断言全红）。已改为 `<int:id>` + `sudo()` + 显式可见性
    过滤，与仓库既有公开页写法一致，好处是不必为一个可选页面放宽整个模型的 ACL。
    用了 sudo 就必须自己写全 `state='published'` **且** `access_level='public'`。

14. **判断"是不是自己的记录"要用 `search` 而不是 `browse().exists()`。**
    `exists()` 不套记录规则，随后读 `user_id` 会先抛出 Odoo 原生 AccessError，用户
    看到的是一段通用权限报错，我写的友好提示根本走不到。已改为
    `search([('id','=',x),('user_id','=',uid)])`——同时套记录规则和显式过滤，
    别人的记录直接查不到。**注意：阻断行为本身一直是对的，错的只是错误信息。**

### 阶段 5 发现

16. **不要给 component 的方法起名 `_abstract`。** arXiv mapper 里有个
    `@staticmethod def _abstract(entry)` 提取论文摘要，结果该 mapper 完全无法解析，
    报 `NoComponentError`。`_abstract` 是框架判断"组件是否抽象"的**类属性**，同名方法
    把布尔值覆盖成函数（真值），`lookup()` 就把它当抽象组件排除。**静态检查、编译、
    类型检查全都发现不了，报错信息与真实原因毫无关联。** 已改名并把保留名清单写进
    steering（ADR-023）。

17. **DOI 正则的右边界不能只排除 ASCII 标点。** `见 10.1038/xxx。` 会把中文句号一起
    吞进 DOI，导致同一个 DOI 算成两个、跨源去重失效。改成"宽匹配 + Python 里截断非
    ASCII + 剥尾部标点（含中文）"，14 个边界用例覆盖。纯正则很难写对这个边界。

18. **`odoo.tools.config` 在 Odoo 19 没有 `.misc`。** 读 odoo.conf 自定义段要用对应
    模块自己暴露的变量（queue_job 是 `odoo.addons.queue_job.jobrunner.queue_job_config`）。

19. **`html_escape` 不在 `odoo.tools.mail`**，在 `odoo.tools.misc`（就是
    `markupsafe.escape` 的别名）。官方模块直接 `from markupsafe import Markup, escape`，
    跟随这个约定更稳。

20. **odoo.conf 缺 arXiv 通道容量。** 测试里加了一项断言直接把它照出来，已补
    `root.infohub.arxiv:1`。这正是"漏配不报错但限速静默失效"的风险，靠断言而不是靠
    文档提醒才可靠。

15. **Odoo 用 REPEATABLE READ 隔离级别。** `odoo shell` 里的事务快照在第一条语句时
    就固定了，HTTP 服务进程之后的提交对它不可见。`env.invalidate_all()` 只清 ORM
    缓存、**不换快照**，所以跨进程验证前必须先 `env.cr.commit()` 结束当前事务。
    这一条一开始让 3 项断言假失败（"标为未读已落库""订阅确实落库""语言偏好"），
    误以为是写入没生效。`http_test.py` 里已封装成 `refresh()`。

21. **数据库层 CHECK 约束会把整个事务置为 aborted。** 测"预期保存失败"时，Python 层的
    `ValidationError` 无害，但数据库层的 CHECK 违反会抛 psycopg2 错误并让后续所有语句
    失败、测试直接崩。必须用 `env.cr.savepoint()` 包住每个预期失败的 create。

### 阶段 6 发现

22. **不要在 `@api.constrains` 里发网络请求。** 核心原本在源的端点约束里做 DNS 解析，
    等于把外部网络的可用性引入数据库写路径：解析器慢就拖住事务，主机名暂时不可解析的
    合法配置还存不下来。已拆成"保存时快速校验（scheme / 字面量 IP / 已知本机名，不发
    DNS）+ 请求时完整校验（完整解析 + 逐跳复检）"。安全属性未被削弱——真正的防护点一直
    是发起请求时（ADR-024）。**这是阶段 6 唯一的核心改动，属于修复而非优化。**

23. **`external_dependencies` 要写 PyPI 包名，不是 import 名。** 写 `dateutil` 会被
    Odoo 警告"不是有效的 PyPI 包名"（它优先用 `importlib.metadata.version()` 查，
    失败才退回 import）。正确写法是 `python-dateutil`。

24. **XML 属性里的裸 `<` 会破坏整个文件。** `placeholder="留空则用页面 <title>"` 让视图
    文件解析失败。必须转义成 `&lt;title&gt;`。

25. **提字段前必须先剔噪声，顺序不能反。** 广告位里常有 `<h1>`，先提标题就会抓到
    "AD HEADLINE"。测试里专门有一项断言广告标题没被当成标题。

## 用户已明确的决定（勿重复询问）

- 多人共享内容，每人选择性订阅自己关注的源/学科/标签
- portal 用户在 **website 端**阅读；内部用户做管理；后台用 Odoo 标准视图，不做自定义 OWL 阅读器
- portal **自助注册**（`auth_signup`）
- 异步用 `queue_job`
- 审核 = 自动 + 规则过滤 + **人工标黑**
- 学科词表用 **arXiv 分类体系**做种子
- 论文**只存 PDF 的 URL**，不下载文件
- arXiv 需要**控制请求速度**
- **不做**站内通知
- **不桥接** `knowledge_base`
- Twitter/X **暂不做**（访问权限未定）
- 模块结构：核心 + 传输层 + 介质层 + 渠道层，见 `design.md` §1.1

## 已核实的技术事实（含出处，勿凭记忆改动）

Odoo 19 源码位于 `/Users/rui/workspace/odoo-projects/odoo-19.0+e.20250917/`，
ORM 已重构进 `odoo/orm/` 包（不再有 `odoo/models.py` 单文件）。

| 事实 | 出处 |
|---|---|
| `models.Constraint(definition, message)` / `Index(definition)` / `UniqueIndex(definition, message)` | `odoo/orm/table_objects.py:79,125,185`；由 `odoo/models/__init__.py` 导出 |
| `Index` 的 definition 形如 `(a, b) WHERE cond`，会被包装成 `INDEX {definition}` | `odoo/orm/table_objects.py:143` |
| AbstractModel 上的 Constraint 会被继承：`_table_objects` 遍历整个 `_model_classes__` | `odoo/orm/model_classes.py:456` |
| `from odoo.fields import Domain`；有 `Domain.TRUE/FALSE`（classproperty）、`Domain.AND/OR`（staticmethod）、`&`/`|`/`~` | `odoo/orm/domains.py:191,272,297,302` |
| **`Domain` 没有 `to_list()`**，转列表用 `list(domain)` | `odoo/orm/domains.py:368` |
| `'any'` / `'not any'` 是标准操作符，用于子查询 | `odoo/orm/domains.py:81` |
| 递归检查用 `_has_cycle()`，不是 `_check_recursion()` | `odoo/orm/models.py:5615` |
| `_read_group(domain, groupby, aggregates)` 返回元组列表，groupby 值是记录 | `odoo/orm/models.py:1861` |
| 排序支持 `nulls first` / `nulls last` | `odoo/orm/models.py:93` `regex_order` |
| `ir.cron` **已无 `numbercall` / `doall`**；数据记录用 name/model_id/state=code/code/interval_number/interval_type/priority | `odoo/addons/base/models/ir_cron.py:78-95`、`data/ir_cron_data.xml` |
| 权限组用 `res.groups.privilege`（含 `category_id`）+ `res.groups.privilege_id` | `odoo/addons/project/security/project_security.xml` |
| `SELF_READABLE_FIELDS` / `SELF_WRITEABLE_FIELDS` 是 `@property`，用属性覆盖扩展 | `odoo/addons/base/models/res_users.py:176,189` |
| 翻译字段存为 jsonb | `odoo/orm/fields_textual.py:66` |
| `Registry.cursor()` 可开独立 cursor；`with cursor() as cr` 正常退出时提交、总是关闭 | `odoo/orm/registry.py:1129`、`odoo/sql_db.py:233` |
| `fields.Datetime.subtract` 存在（继承自 `BaseDate`） | `odoo/orm/fields_temporal.py:33` |
| `widget="json"` 已注册，支持 json 类型字段 | `odoo/addons/web/static/src/views/fields/json/json_field.js` |
| 表单聊天区用 `<chatter/>` 标签 | `odoo/addons/project/views/project_project_views.xml:139` |
| `with_delay(channel=..., description=..., identity_key=...)` 后接 `._method()`；无需声明 `queue.job.function`（缺失时走默认配置） | `knowledge_base_vector_store/models/knowledge_vector.py:88`、`queue_job/models/queue_job_function.py` `job_config` |
| 通道以 `queue.job.channel` 数据记录声明，`parent_id` 指 `queue_job.channel_root` | `knowledge_base/data/queue_data.xml` |
| **通道容量由 odoo.conf `[queue_job] channels` 或 `ODOO_QUEUE_JOB_CHANNELS` 配置，不是 DB 字段**，默认 `root:1` | `queue_job/jobrunner/runner.py:164-168` |
| component 用 `_inherit` 字符串建立注册表关系，Python 类继承不算数 | `component/core.py:828-890` `_build_component` |
| `component()` 多匹配抛 `SeveralComponentError`，内置消歧只按 collection 和 model | `component/core.py` `_filter_components_by_collection` / `_filter_components_by_model` |
| 仓库 manifest 约定：`version` `19.0.1.0.0`、`license` `LGPL-3`、`author` `quick-sort@outlook.com` | `base_pgvector/__manifest__.py` |

## 验证手段

| 手段 | 覆盖 | 怎么跑 |
|---|---|---|
| 容器安装 + `-u all` | 装载期错误：视图 RNG、约束 SQL、component 注册表构建、数据文件、资产打包、manifest RST | 见上方"测试环境" |
| `smoke_test.py` | 54 项后端：三轴解析、可解析性约束、SSRF、流水线、去重、审核标黑、订阅时间线、权限越权、失败簿记独立事务 | `odoo shell < smoke_test.py` |
| `http_test.py` | 54 项前端：路由可达、匿名重定向、个性化过滤、打开即已读、筛选搜索分页、jsonrpc、CSRF、越权隔离、公开页可见性、注册限流、读者初始化 | 需先起临时 HTTP 服务 |
| `stage4_test.py` | 57 项：规则条件组合、五种动作、终结型/标注型、`stop_after`、保存期校验、试运行、正文提取候选与四类失败分支、核心独立性 | `odoo shell < stage4_test.py` |
| `stage5_test.py` | 101 项：学科树与映射、DOI/arXiv ID 归一化 20 个边界、身份计算 10 种情形、载荷落库、arXiv mapper 与 classifier、限速通道路由（含 odoo.conf 断言）、端到端流水线、**跨源收敛与反证** | `odoo shell < stage5_test.py` |
| `stage6_test.py` | 56 项：选择器保存期校验、三种分页、两阶段抓取与字段提取、只抓新链接、同域限制、噪声剔除顺序、`list_only`、`render_js` 报错、`web+paper` 的 DOI 收敛、**零代码接入验收** | `odoo shell < stage6_test.py` |
| `stage7_test.py` | 70 项：摘要内容筛选六维度、按 (用户,周期) 分组、幂等与三种状态语义、邮件渲染、cron 重跑安全、LLM 一次性提问姿势、两条失败路径、成本闸门、零样本归类事后校验 | `odoo shell < stage7_test.py`（LLM 全 mock，无费用） |
| 真卸载验证 | `button_immediate_uninstall` 后核心是否仍完整（R6.4） | 见阶段 4 记录 |
| 实网抓取 | 真实 HTTP 路径、feedparser 解析、条件请求与兜底增量 | 见 progress 历史 |
| `check_refs.py` | 视图/ACL/记录规则/数据文件里的模型与字段引用 | `python3 check_refs.py`（不需容器） |

**仍未覆盖**：并发抓取、queue_job 实际派发与 `identity_key` 防重入队、前端 JS 交互
（只测了后端端点，没跑浏览器）、大数据量下的查询计划、`infohub_fulltext` 与
`infohub_arxiv` 对真实站点/真实 API 的效果（都用注入响应验的逻辑分支）。

## 开放风险

| 风险 | 说明 |
|---|---|
| `feedparser` 未持久化 | 容器里手工 pip 装的，重建即失效。`infohub_rss` 与 `infohub_arxiv` 都依赖它。建议加 Dockerfile 或 requirements.txt。`trafilatura` 镜像自带，不受影响 |
| odoo.conf 改动未重启生效 | 已把 `root.infohub:2,root.infohub.arxiv:1` 写进 `~/workspace/odoo-projects/odoo.conf`，但**常驻容器需重启才生效**。我没有擅自重启 |
| queue_job 派发未验证 | 四套测试都直接调 `_fetch()` / `enrich()`，绕过了 `with_delay`。`identity_key` 防重入队、通道容量的**实际**限速效果都还没实测 |
| arXiv 未对真实 API 验证 | 逻辑分支全覆盖，但真实 API 的字段差异、限速响应（429）、大结果集翻页都没实测。上线前应挑一个板块真跑一轮 |
| 正文提取未在真实站点上验证 | 同上，不同站点的提取质量差异很大 |
| `_queue_channel` 未委托给 component | 已知设计气味，渠道模块要写 if 守卫。复审触发条件：出现第二个需要专用通道的来源方（ADR-022） |
| ReDoS 未根治 | 规则正则只限制了输入长度（10 万字符），Python `re` 无超时机制 |
| 前端 JS 未跑浏览器测试 | `infohub_reader.js` 的收藏切换与订阅表单联动只验证了后端端点 |
| 载荷表 join 成本 | 已用 store=True 的 related 缓解（title/published_at/source_id/state），但大数据量下的实际查询计划未验 |
| 作者消歧只做保守归一化 | 同名不同人不会被合并（好），但同一人的不同写法（缩写、姓名顺序）也不会合并。需要精确消歧要接 ORCID |
| 记录规则的安全论证有前提 | ADR-015 成立的前提是"内容都是公开网页信息"。接入付费或内部机密源时必须重新评估——公开学科页用了 sudo，届时一并复查 |
| 邮箱验证不是准入门槛 | Odoo 自助注册立即创建账号，只发确认邮件 |
| 公开页不进 sitemap | 为任意 id 生成 sitemap 需要 callable 生成器，当前 `sitemap=False` |
| DNS rebinding 残留风险 | `url_guard.py` 在请求前校验解析结果，但无法防御校验后改解析。**若将来允许 portal 用户自建源，必须重新评估** |
| 选择器随站点改版失效 | 网页采集固有的维护成本。缓解：配置的「备注」记录结构假设；抓取日志 `item_found` 为 0 即失效信号。建议对 web 源配告警 |
| `render_js` 未实现 | 需要 JS 渲染的站点当前直接报错。环境里有 playwright（见 `.playwright-mcp/`），将来可接 |
| 无 Odoo 原生测试 | 按用户要求未自动添加 `tests/`。六个脚本都是 shell 驱动，不进 CI。**排期已结束，建议现在决定是否转成 `TransactionCase` / `HttpCase`** |
| LLM 未对真实模型验证 | 阶段七的 LLM 调用全部 mock（避免产生费用）。真实模型的输出质量、超时行为、费率都没实测。上线前应先小批量试跑并核对账单 |
| 摘要邮件未实测投递 | 测试只验证了 `mail.mail` 记录被正确创建，没有真发。SMTP 配置、退信处理、垃圾邮件判定都没验 |
| LLM 与正文提取的顺序 | 两者都是 enricher，执行顺序不保证。先提正文再摘要质量更好，反之只能看到 RSS 的一两句。同时启用的源要接受首轮质量偏低 |
