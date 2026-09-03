---
inclusion: fileMatch
fileMatchPattern: '{infohub*/**,.kiro/specs/infohub/**}'
---

# InfoHub 开发约束

在线信息聚合模块组（RSS 新闻、博客、论文、社交），多人按学科/标签订阅，portal 用户在 website 端阅读。

## 文档索引（改代码前先读）

| 文件 | 内容 |
|---|---|
| `.kiro/specs/infohub/requirements.md` | 需求 R1–R13、非功能需求 N1–N10 |
| `.kiro/specs/infohub/design.md` | 三轴组合、数据模型、component 扩展点、流水线 |
| `.kiro/specs/infohub/decisions.md` | **被否决的方案与理由**，改设计前必读 |
| `.kiro/specs/infohub/tasks.md` | 任务清单与阶段划分 |
| `.kiro/specs/infohub/progress.md` | 当前进度与交接状态 |

**不要在未读 `decisions.md` 的情况下推翻既有设计**——多数"更好的想法"已被评估并记录了否决理由。

## 不可违背的架构约束

1. **三轴组合**：`infohub.source = medium × transport × provider`，三者正交、无跨轴继承。一个模块原则上只在一个轴上贡献实现。轴内继承允许，跨轴继承禁止。（ADR-002）
2. **调用方不得出现来源判断分支**。任何 `if source.provider == ...` / `if source.transport == ...` 都是设计错误，应改为新增 component。（ADR-001）
3. **`provider` 必填，默认 `generic`**。留空会导致多个 mapper 同时命中并抛 `SeveralComponentError`。（ADR-007）
4. **时间线是拉取式**。不得为「用户 × 条目」预生成行。（ADR-003）
5. **per-user 状态只进 `infohub.item.read`**，不得在 `infohub.item` 上加 `is_read` 这类字段。（ADR-004）
6. **介质特有字段进各自载荷表**（继承 `infohub.medium.payload`），不得加到 `infohub.item` 上。（ADR-005）
7. **去重身份由 medium component 的 `identity()` 计算**，不得在 provider 或核心里硬编码。（ADR-006）
8. **核心不得依赖 `infohub_filter`**。`_moderate()` 默认发布；卸载 filter 后核心必须仍能工作。（ADR-009）
9. **新增来源优先加数据记录，不加模块**。建模块前先对照 ADR-018 的判定表。

## 安全红线

- 源 URL 由用户输入、服务端出网 → **SSRF 防护必须走核心 HTTP 组件基类**：限 http/https、拦截私有网段/环回/链路本地、重定向逐跳复检。禁止绕过基类直接 `requests.get`。
- 正文是第三方 HTML 且渲染到**公开页面** → `fields.Html(sanitize=True)`；QWeb 一律 `t-out`，**禁止 `t-raw`**。
- 所有出网请求必须有超时与响应体积上限。
- `infohub.credential` 仅 `group_manager` 可读，对 portal 和 `group_user` 无权限。
- `infohub.subscription` 和 `infohub.item.read` **必须**有 `user_id = user.id` 记录规则，否则 portal 用户可读改他人数据。

## Odoo 19 与仓库约定

- 版本 `19.0.1.0.0`、license `LGPL-3`、author `quick-sort@outlook.com`
- SQL 约束用 `models.Constraint`（`_sql_constraints` 已不支持）；复合索引用 `models.Index`
- 域运算用 `from odoo.fields import Domain`（`odoo.osv.expression` 已过时）
- 列表视图用 `<list>`（不是 `<tree>`）；动态属性直接写 `invisible="..."`（不是 `attrs`）
- 聚合用 `aggregator=`（不是 `group_operator=`）
- 删除校验用 `@api.ondelete(at_uninstall=False)`（不要覆盖 `unlink`）
- Python 依赖写进 `__manifest__.py` 的 `external_dependencies`
- 目录结构 `models/ components/ views/ security/ data/`

## queue_job 用法

```python
record.with_delay(
    channel="root.infohub",
    description=_("..."),
    identity_key="infohub-fetch-%s" % record.id,   # 防止同一源重复入队
)._method()
```

通道在 `data/queue_data.xml` 以 `noupdate="1"` 声明，`parent_id` 指向 `queue_job.channel_root`。

**通道容量是 odoo.conf 配置，不是 DB 字段**：`[queue_job] channels = root:4,root.infohub.arxiv:1`。arXiv 限速依赖这一行，漏配则静默失效。（ADR-012）

## component 框架陷阱

`WorkContext.component()` 匹配到多个候选会抛 `SeveralComponentError`，其内置消歧只按 collection 和 model（见 `component/core.py` 的 `_filter_components_by_collection` / `_filter_components_by_model`），**在三轴场景下无法消歧**。因此匹配键必须由 `_component_match` 保证唯一。

**component 类里禁止用这些方法名**，它们是框架保留的类属性：

`_abstract`、`_name`、`_inherit`、`_collection`、`_usage`、`_apply_on`、`_register`、`_module`

其中 `_abstract` 最危险：框架用它判断组件是否抽象，定义同名方法会把布尔值覆盖成函数（真值），于是 `lookup()` 把该 component 当抽象组件排除。表现是"明明写了却报 `NoComponentError`"，与真实原因毫无关联，静态检查也发现不了。（ADR-023）

component 的继承必须用 `_inherit` 字符串，**Python 类继承不算数**——框架只按 `_inherit` 建注册表关系。写法：`class X(AbstractComponent)` + `_inherit = "父组件名"`。
