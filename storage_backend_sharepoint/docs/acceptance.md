# Storage Backend SharePoint — 验收标准

前置：安装 `microsoft_graph`（本模块依赖它）。测试全 mock
`microsoft.graph.service`，不触网。

## AC-1 配置校验

`_sharepoint_validate_configuration`：backend 无 application 或无 drive_id →
`UserError`；backend_type 非 sharepoint → `UserError`；配齐则通过（含委托
应用校验）。 — `test_validate_configuration_missing_application`、
`test_validate_configuration_missing_drive`、
`test_validate_configuration_rejects_other_type`

## AC-2 授权委托核心

`action_sharepoint_authorize` 调用 `microsoft.graph.service` 的
`_authorization_action(应用, redirect_to=backend 表单)`（mock 验证参数）。
— `test_authorize_delegates_to_graph_service`

## AC-3 当前用户已授权状态

`sharepoint_current_user_authorized`：当前用户在 backend 的应用下有凭证 →
True；换到无凭证用户 → False。 — `test_current_user_authorized_compute`

## AC-4 adapter 绑定 backend 的应用

adapter 的 Graph 调用以 `backend.sharepoint_application_id` 作为第一参数交给
`microsoft.graph.service._request`（mock 断言）；无 application 的 backend →
`AccessError`。 — `test_adapter_requests_use_backend_application`、
`test_adapter_requires_application`

## AC-5 drive 路径端点构造

`_path_endpoint`：库根 + 相对路径 + `:/path:` 语法、根 item 变体、`_rooted_path`
对 `directory_path` 的拼接。 — `test_path_endpoint_construction`

## AC-6 Read Only 写保护

read_only backend：`open(path, "wb")`、`delete`、`rename`、`rmdir` →
`AccessError`；读操作不受影响。 — `test_read_only_blocks_write`

## 运行方式

```bash
docker exec odoo odoo -c /etc/odoo/odoo.conf -d <db> \
  -i storage_backend_sharepoint --test-enable --test-tags /storage_backend_sharepoint \
  --stop-after-init --workers=0 --no-http
```

（`-i` 会先装依赖 `microsoft_graph`。）
