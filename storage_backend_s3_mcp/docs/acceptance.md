# Storage Backend S3 MCP — 验收标准

## AC-1 组件注册

组件以 `_usage = "amazon_s3"` 注册且继承了 `s3.adapter`（`_inherit` 生效，
非 Python 继承）。 — `test_component_extends_s3_adapter`

## AC-2 presign 委托

`presign_upload/presign_download` 调用 boto3 client 的
`generate_presigned_url`（mock 验证：`put_object` / `get_object`、bucket、
映射后的物理 key、TTL 参数）。 — `test_presign_upload_calls_boto3`、
`test_presign_download_calls_boto3`、`test_presign_ttl_capped`

## AC-3 物理路径映射

传入逻辑路径，boto3 收到 `_gzip_physical` 映射后的物理 key
（`.gz` 后缀场景）。 — `test_gzip_key_mapping_passed_to_boto3`

## AC-4 端到端工具路径

`storage_get_upload_url` 对 S3 backend 返回 presigned URL（非中转 token URL）。
boto3 全 mock。 — `test_tool_returns_presigned_url_for_s3`

## 运行方式

```bash
docker exec odoo odoo -c /etc/odoo/odoo.conf -d <db> \
  -i storage_backend_s3_mcp --test-enable --test-tags /storage_backend_s3_mcp \
  --stop-after-init --workers=0 --no-http
```

boto3 client 与凭证全 mock，无网络、无真实 S3。
