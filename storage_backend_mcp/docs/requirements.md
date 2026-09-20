# Storage Backend MCP — 业务需求

## 要解决的问题

让 agent（MCP 客户端、Odoo 内部 agent）能够向 `storage.backend` 上传/下载文件，
并让上传的文件可以被**另一个工具**引用消费。

典型场景：

1. agent 产出文件（报告、CSV、图片），写入某个后端的指定路径。
2. agent 上传一个载荷（如 skill 的 zip 包），随后调用另一个工具
   （如未来的 skillhub）时**引用这个文件**。

## 范围

**做**：

- 提供一组 `storage_*` MCP/LLM 工具（浏览、读、写、删除、签发上传/下载 URL）
- 上传/下载以**临时 URL** 为载体：agent 拿 URL 后用 curl/HTTP 直传，
  字节流不过 MCP JSON-RPC 通道
- 无原生签名能力的后端（filesystem/sftp/ftp/…）走 Odoo 中转 controller
  （capability token 鉴权）
- 暂存上传（staging）：返回 `file_id` 作为跨工具引用的货币，
  供下游工具（skillhub 等）消费
- 每后端读写开关（默认关）
- 提供"原生签名 URL"扩展点（S3 presign 由 bridge addon `storage_backend_s3_mcp` 兑现）

**不做**：

- 不做 MCP 服务端（那是 `llm_mcp_server` 的事；本 addon 只贡献 `llm.tool` 行）
- 不把 `llm_mcp_server`、`storage_backend_s3`（boto3）拉进依赖
- 不做分块/断点续传（大小上限内的单次 HTTP 传输已覆盖 agent 日常载荷）
- 不用 `ir.attachment` 当存储路径（会绕开 `storage.backend`，分叉出第二条真相）
- 不新写路径安全逻辑（复用 `storage.backend` 公共 API 的既有校验）

## 非功能要求

1. **依赖隔离**：core 只依赖 `storage_backend` + `llm`，零新增 Python 依赖。
2. **离线可测**：不联网、无 API key、无 boto3 也能全量跑测试。
3. **可审计**：上传→消费全链路可追溯到 MCP 用户（token/upload 行携带 `create_uid`，
   与 `llm.mcp.tool.call` 审计行成链）。
