# Storage Backend MCP — 开发约束（自动加载）

设计文档见 `docs/`，这是唯一要求来源，改代码前先读：

- `docs/requirements.md` — 业务需求与边界
- `docs/design.md` — URL broker 架构、token/upload 模型、被否决方案
- `docs/acceptance.md` — 验收标准（QC 唯一依据）

红线：

1. **字节流不过 MCP 通道**：上传/下载只签发 URL（presign 或一次性 capability token），禁止 base64 进 tool arguments。
2. **路径安全零新写**：一律走 `storage.backend` 公共 API，`..`/绝对路径由 `_check_relative_path` 拒绝。
3. **core 依赖只有 `storage_backend` + `llm`**：不依赖 `llm_mcp_server`/`storage_backend_s3`，不新增 Python 依赖。
4. **消费方只收 `file_id`**：`storage.upload.consume()` 是唯一消费入口，禁止把 `(backend, path)` 当跨工具引用。
