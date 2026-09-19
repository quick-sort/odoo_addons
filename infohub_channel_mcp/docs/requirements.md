# InfoHub MCP Channel — 业务需求

## 要解决的问题

让 InfoHub 能从第三方 MCP 工具（或数据 API）拉取新闻，汇入池子。

## 范围

**做**：

- 提供 `mcp` 渠道类型
- 通过 `llm.mcp.client` 调用远端工具取数
- 防御式归一化工具返回（形状未知）
- 工具返回的每个字段保留进 `raw_data` 供过滤

**不做**：

- 不把 `llm` 依赖引入 core（只在本 addon 内）
- 不复刻凭证——端点/API key 留在 `llm.mcp.client` 上
- 不做 MCP 服务端（那是 `llm_mcp_server` 的事）

## 非功能要求

1. **依赖隔离**：本 addon 是唯一依赖 `llm` 的 infohub addon，core 不。
2. **容错**：工具返回未知形状 → 得到空结果，不抛异常。
3. **离线可测**：MCP 客户端全部 mock，无网络、无费用。
