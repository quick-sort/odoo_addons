# Storage Backend S3 MCP — 系统设计

## 定位

`storage_backend_mcp` 的 bridge：把 core 定义的"原生签名 URL"扩展点
（`presign_upload/presign_download`，默认返回 None → 走中转）在 S3 上兑现为
boto3 presigned URL。字节直连 S3，不过 Odoo。

与 `llm_store`+`llm_pgvector`、`llm_knowledge`+extractor 同构的 provider bridge。

## 组件

单一组件：

```python
class S3AdapterPresign(Component):
    _name = "s3.adapter.presign"
    _inherit = "s3.adapter"        # 继承 vendored 的 s3.adapter，不改其文件
    _usage = "amazon_s3"           # 保持同一 usage：backend_type → 组件查找不变
```

- 复用 `s3.adapter` 现成的 boto3 client 工厂与凭证字段（`aws_bucket` 等），
  不复制任何配置。
- `presign_upload(path, expires)` → `generate_presigned_url("put_object", ...)`；
  `presign_download(path, expires)` → `get_object`。
- key 经 core 的 `storage.backend.presign_*` 公共方法做过 `_gzip_physical`
  映射后传入——物理 key 与 `open()` 实际读写的 key 一致（`.gz` 后缀对齐）。
- TTL 上限与 core 一致（1 小时），超过则收敛到上限。

## 与 core 的分工

| 关注点 | core | 本 bridge |
|---|---|---|
| 工具面、token、中转 controller、upload 暂存 | ✓ | |
| presign 扩展点（默认 None） | ✓ | |
| S3 presign 实现 | | ✓ |

加其他对象存储 bridge（OSS/MinIO/…）时，各自新 bridge，core 与本 addon 均零改动。

## overwrite 语义

S3 presign PUT 天生覆盖（last-write-wins）。v1 与 core 一致：签发时查
`file_exists`（走 Odoo）并对已存在文件在未显式 `overwrite=True` 时拒绝；
接受签发后到上传完成之间的竞态。把 `IfNoneMatch: "*"` 纳入签名头留作
refinement。

## commit 语义

presign 路径下字节不经 Odoo，core 的 `storage_commit_upload` 在 commit 时调
`adapter` 流式读对象算 sha256（`open(path, "rb")` 分块，不进内存）。
本 bridge 无需额外代码——该逻辑在 core，adapter 的 `open` 契约已足够。

## 被否决的方案

| 方案 | 否决理由 |
|---|---|
| presign 写进 core | core 被迫依赖 boto3/`storage_backend_s3`，纯 filesystem 部署受害。 |
| 复制 S3 凭证/配置到新模型 | 凭证双处真相；组件继承复用 `s3.adapter` 现有字段即可。 |
| 用新的 `_usage` 注册 | `storage.backend._get_adapter` 按 `backend_type` 查 usage，换名会查不到组件。 |
