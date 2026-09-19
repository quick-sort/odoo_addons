# InfoHub MCP Channel — 系统设计

## 取数

`infohub.fetch.mcp` 的 `fetch_news`：

1. 校验 channel 配了 `mcp_client_id` 和 `mcp_tool_name`，缺则抛 `UserError`
2. 拼 `dateFrom`/`dateTo` 参数（有则传，无则省）
3. `mcp_client_id.call_tool(tool_name, arguments)` —— 走 `llm.mcp.client`
4. 归一化返回，转成 item dict 列表

## 结果归一化（防御式）

MCP 协议不描述工具返回什么，所以按三级 fallback 处理：

- `_as_document(payload)`：解开 `{"result": ...}` 包裹；字符串则 JSON 解码；
  解不了（纯文本回复）→ `None`
- `_as_items(document)`：裸列表直接用；字典则探测常见信封键
  （`records`/`items`/`data`/`results`/`news`/`list`/`entries`）；其它 → 空
- 每个 item dict 保留全部原始字段进 `raw_data`

收益：工具改了信封键，这里退化成"没有条目"而不是抛错。

## 依赖隔离

`infohub_channel_mcp` 的 `depends` 含 `llm`，而 core `infohub` 的 `depends` 只含
`base`/`component`/`queue_job`。有测试断言 core 的依赖列表不含 `llm`。

## 组件扩展

- `infohub.fetch.mcp`：出网取数 + 归一化
- `infohub.content.mcp`：从工具返回的 raw dict 取 subject/source/date/url/content

## 被否决的方案

| 方案 | 否决理由 |
|---|---|
| 把 `llm.mcp.client` 依赖放进 core | 绝大多数部署只要 RSS/email，不该为此装 LLM 栈。 |
| 假定工具返回固定 schema | MCP 不约束返回，固定 schema 会在工具改版时崩。防御式归一化更稳。 |
| 在 channel 上存端点/API key | 凭证会重复；复用 `llm.mcp.client` 是单源。 |
