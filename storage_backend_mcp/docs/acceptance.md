# Storage Backend MCP — 验收标准

## AC-1 工具注册

全部 `storage_*` 工具被 `@llm_tool` 扫描注册为 `llm.tool` 行（executor
`model_method`，source `code`）。 — `test_all_storage_tools_registered`

## AC-2 治理开关

- 读写开关默认 False；关闭时对应工具抛 `UserError`
- 非授权用户（非 `group_system`）调工具走 ORM `AccessError` —
  `test_governance_flags_default_off`、`test_write_tool_rejected_when_disabled`、
  `test_access_error_for_unauthorized_user`

## AC-3 URL 签发多态

- 默认组件（无 presign 能力）：`presign_upload` 返回 None → 工具走中转，
  返回含一次性 token 的 URL 与 curl 命令
- monkeypatch adapter 返回假 presign URL → 工具原样返回（含 method/headers）—
  `test_fallback_to_relay_when_no_presign`、`test_presigned_url_passthrough`

## AC-4 capability token

- 按 hash 查找命中；错误 token 404
- 过期 token 拒绝
- 上传 token 单次使用，重放拒绝
- token 创建时拒绝 `..`/绝对路径（复用 `_check_relative_path`）—
  `test_token_lookup_by_hash`、`test_expired_token_rejected`、
  `test_upload_token_single_use`、`test_token_rejects_path_escape`

## AC-5 中转 controller 往返（HttpCase）

- PUT 后 GET 读回，字节一致，sha256 与 commit 返回一致
- 超过 `max_size_bytes` 中止并删半成品
- gzip 扩展映射：presign/中转路径的物理 key 与 `open()` 一致（`.gz` 后缀）—
  `test_upload_download_roundtrip`、`test_oversize_aborted_and_cleaned`、
  `test_gzip_physical_path_consistent`

## AC-6 暂存上传协议

- stage 返回 file_id 与上传 URL，路径落在 `.mcp_staging/` 前缀下
- 中转路径：PUT 时边流边算 hash，commit 直接确认
- presign 路径：commit 时 adapter 流式读对象算 hash（mock adapter 验证调用）
- commit 前 state 为 pending，commit 后 staged
- consume 只接受 staged；consumed 后不可重放；`consumed_model/res_id` 落档
- 非 owner 不能 commit/consume 他人 upload —
  `test_stage_upload_returns_file_id_and_url`、`test_commit_hash_relay_vs_presign`、
  `test_consume_requires_staged_and_is_single_shot`、`test_ownership_enforced`

## AC-7 GC

- 过期 token 行被 cron 清理
- 过期未消费的 upload 行被清理，staging 对象删除 —
  `test_expired_tokens_pruned`、`test_expired_uploads_pruned_with_objects`

## AC-8 overwrite 保护

直写签发时目标已存在且未显式 `overwrite=True` → 拒绝。 —
`test_upload_url_requires_overwrite_flag`

## 运行方式

```bash
docker exec odoo odoo -c /etc/odoo/odoo.conf -d <db> \
  -i storage_backend_mcp --test-enable --test-tags /storage_backend_mcp \
  --stop-after-init --workers=0 --no-http
```

filesystem backend + tmpdir（抄 `storage_backend/tests/common.py`）；
presign 与 adapter 全 mock，无网络、无 API key、无 boto3。
