# Storage Backend S3 MCP — 业务需求

## 要解决的问题

`storage_backend_mcp` 的上传/下载走中转 controller 时，字节流要过一遍 Odoo。
S3 后端有原生签名能力（presigned URL），应让字节**直连对象存储**，
不经 Odoo 中转。

## 范围

**做**：

- 覆盖 `s3.adapter` 的 `presign_upload/presign_download`，用 boto3
  `generate_presigned_url` 产出直连 S3 的临时 URL
- 上传/下载对称覆盖

**不做**：

- 不在 core（`storage_backend_mcp`）里出现 boto3 / `storage_backend_s3` 依赖
- 不改 vendored 的 `storage_backend_s3` 代码（组件继承扩展）
- 不做 Odoo 侧尺寸上限（presign 直连固有；可日后 bucket policy 收紧）
- 不引入新的 S3 客户端配置（复用 `s3.adapter` 现成的 client 工厂与凭证字段）

## 非功能要求

1. **纯增量**：不装本 addon 时 S3 后端照常走中转，一切不变。
2. **离线可测**：boto3 client 全 mock，无网络、无真实凭证。
3. **依赖零新增**：boto3 随 `storage_backend_s3` 已声明。
