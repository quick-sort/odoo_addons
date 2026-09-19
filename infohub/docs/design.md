# InfoHub — 系统设计

## 数据模型

### infohub.source（来源）

谁拥有这条新闻。字段：`name`（必填）、`url`（主页）、`description`（识别线索，
如域名或发件人地址）。

### infohub.channel（渠道）

怎么拿到新闻。继承 `collection.base`（component 的 collection）。字段：

- `channel_type`：Selection，**core 置空**，由各渠道 addon `selection_add` 填充
- `name`、`active`、`enable_cron`
- `filter_domain`：入库前对每条原始条目求值的 Odoo 域
- 健康状态：`last_run_at` / `error_count` / `last_error`

**core 不预置任何渠道专属字段。** RSS 的 `rss_url`、MCP 的 `mcp_client_id` 都由
各自 addon 用 `_inherit` 追加。

### infohub.item（池子）

一条新闻。字段：`channel_id`、`source_id`、`published_at`、`title`、`content`、
`content_text`、`url`、`external_id`、`raw_data`、`state`、`error_message`。

- 唯一约束 `(channel_id, external_id)`：渠道内去重。
- 时间线索引 `(published_at DESC, id DESC)`。

## 渠道扩展点

core 定义两个抽象 component，每个渠道 addon 各自实现：

- `infohub.fetch` —— `fetch_news(date_from, date_to)` 返回 `(raw, items)`
- `infohub.content` —— 解析各渠道自己的 `raw_data` 形状（subject / date /
  source / url / build_content）

### 解析按 usage 后缀，不做 _component_match 消歧

```python
WorkContext(model_name=..., collection=channel).component(
    usage=f"infohub.fetch.{channel.channel_type}")
```

usage 由类型后缀天然唯一，绕开了 `SeveralComponentError`——不需要"provider 必填
默认值"那类补丁（这是旧三轴设计最痛的一处）。

## 入库管线

`channel._ingest(items)` 把渠道返回的原始条目归一化并入库：

1. 归一化 raw payload（`entry["raw_data"]` 或 entry 本身）
2. 过滤（`filter_domain`）
3. 取标题（entry 的 `title` 或 `content.subject()`）
4. 渠道内去重（external_id）
5. 建 item（`content.build_content()` 渲染正文）

## 关键取舍与理由

### 为什么 source 和 channel 分开，而不是一个"来源=渠道"的字段

同一出版方可通过多种方式到达。合并成一个字段无法表达"同一个网站 A，既走 RSS
又走邮件"。这是本轮重设计推翻旧三轴模型的核心动机之一。

### 为什么 core 不依赖 llm

MCP 渠道需要 `llm.mcp.client`，但绝大多数部署只需要 RSS/email。把 llm 依赖
封闭在 `infohub_channel_mcp` 内，core 保持轻量（有测试断言 core 的依赖列表
不含 `llm`）。

### 为什么失败簿记走独立 cursor

`queue_job` 失败会回滚调用方事务，写在同事务里的 `error_count` 会跟着消失，
自动停用永远触发不了。独立 cursor 提交，簿记才能存活。

### 为什么出网要手跟重定向

`requests` 的 `allow_redirects=True` 只校验第一个 URL。恶意源可以 302 到
`127.0.0.1` 或 `169.254.169.254`。手工逐跳重检（`allow_redirects=False`）每跳都过
`url_guard`。

## 被否决的方案

| 方案 | 否决理由 |
|---|---|
| 三轴 `medium × transport × provider` | 旧设计。12 条预设只用了 4 种组合，provider 轴只有一个非 generic 值，却迫使 mapper 双轴、provider 必填默认值。复杂度与收益严重不匹配。 |
| 来源=渠道（合并成一个字段） | 无法表达同一出版方多路到达（见上）。 |
| 用 `_component_match` 消歧 | 框架在 collection/model 之外无法消歧，会抛 `SeveralComponentError`，需要额外补丁。usage 后缀更直接。 |
| 给 `infohub.item` 加 `mail.thread` | 会让 chatter 三张表随新闻条数膨胀。改用中转模型（见 email 渠道 addon）。 |
