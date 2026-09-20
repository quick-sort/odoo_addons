# Storage Backend S3 MCP — 开发约束（自动加载）

设计文档见 `docs/`，这是唯一要求来源，改代码前先读：

- `docs/requirements.md` — 业务需求与边界
- `docs/design.md` — bridge 定位、组件继承、与 core 分工
- `docs/acceptance.md` — 验收标准（QC 唯一依据）

红线：

1. **不改 vendored 的 `storage_backend_s3`**：扩展只靠组件继承（`_inherit = "s3.adapter"`，`_usage` 保持 `amazon_s3`）。
2. **零新增依赖与配置**：boto3/凭证随 `storage_backend_s3` 复用，不复制任何配置。
