# InfoHub — 业务需求

## 要解决的问题

把来自多个地方的新闻汇集进**同一个池子**，统一查看。

## 核心概念：来源与渠道是两个正交维度

- **来源（source）**：新闻属于谁——一个出版方（期刊、新闻网站）。回答"这是谁的"。
- **渠道（channel）**：怎么拿到它——RSS 订阅、入站邮件、第三方 API。回答"怎么来的"。

两者刻意分开：同一个出版方可能既通过 RSS 又能通过邮件订阅到达。因此一条条目
同时记录 `source_id`（谁的）和 `channel_id`（怎么来的）。同一篇文章经 RSS 和
邮件两条路进来，就是两条仅在 channel 上不同的记录。

## 范围边界

**做**（本 addon，即 core）：

- 定义 source / channel / item 三个模型
- 定义渠道的扩展点（fetch / content component）
- 提供把"渠道取回的原始条目"归一化并入库的公共管线
- 渠道内去重（`(channel_id, external_id)` 唯一）
- 出网 URL 的安全校验（SSRF 防护，供各渠道复用）

**不做**（core 明确不包含，由其他 addon 承担）：

- 任何具体渠道的实现（RSS / email / MCP 各是一个独立 addon）
- 任何 LLM 依赖（渠道 addon 按需依赖 llm：mcp 直接、email 经 `infohub_agent`，core 不）
- 订阅、读者管理、阅读状态、摘要邮件、前端阅读页面——这些是未来独立 addon 的事

## 非功能要求

1. **可扩展**：新增一个渠道不改 core，只需一个新 addon 挂上 `selection_add` 和
   两个 component。
2. **核心保持干净**：core 不预置任何渠道专属字段（`rss_url`、`mcp_client_id` 等），
   由各渠道 addon 用 `_inherit` 自己加。
3. **失败可观测**：抓取失败要留下可查询的 `error_count` / `last_error`，且不被
   事务回滚吞掉。
4. **安全**：所有服务端出网都要过 `url_guard`，阻止 SSRF。

## 明确不做的（防范围蔓延）

- 不做跨渠道去重（同一篇文章经 RSS 和邮件进来，就是两条——这本身是设计意图，
  见 design.md）。
- 不做站内通知、不做 PDF 下载。
- 不做前端自定义阅读器（后台用标准视图即可）。
