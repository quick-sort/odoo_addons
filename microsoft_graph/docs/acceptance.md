# Microsoft Graph — 验收标准

## AC-1 授权动作生成正确的 OAuth URL

`_authorization_action` 产出指向租户 authorize 端点的 act_url，含
client_id / scope / redirect_uri / state / S256 code_challenge（challenge 可由
落库的 verifier 重算）；state、verifier、state 有效期已写入 (应用, 当前用户)
凭证。 — `test_authorization_action_builds_pkce_url`

## AC-2 回调完成授权并绑定 Entra 身份

mock token 端点与 `/me`：`_complete_authorization` 用 state 找到凭证、
以 code+verifier 换 token、把 entra_oid 与 token 写入凭证、清空流程状态。
— `test_complete_authorization_stores_tokens`

## AC-3 流程状态一次性与时效

state 不存在或已过期 → `AccessError`（过期 state 由 10 分钟 TTL 兜底；
成功路径才清状态）。 — `test_complete_authorization_invalid_state`、
`test_complete_authorization_expired_state`

## AC-4 Entra 身份不可换绑

凭证已有 entra_oid，再次以不同 oid 存 token → `AccessError`。
— `test_store_tokens_rejects_identity_change`

## AC-5 token 缓存与刷新

token 未过期 → 直接返回，不发 HTTP；过期或缺 refresh_token 相关状态 →
走刷新；刷新返回的 refresh_token 为空时保留旧值。 —
`test_cached_token_avoids_http`、`test_expired_token_refreshes`

## AC-6 invalid_grant 报错

刷新收到 `invalid_grant` → `UserError`（带 error_code）。凭证不做失败时
清理（见 design.md 被否决表：write-before-raise 在调用方回滚下永不生效）。
— `test_invalid_grant_raises_error`

## AC-7 Graph 请求语义

`_request`：401 → 强制刷新后重试成功；429 → 按 `Retry-After` 睡眠重试；
404 → `FileNotFoundError`；403 → `AccessError`；非 2xx → `UserError` 且消息
来自 Graph error 负载；非 Graph 域的续链 URL → `AccessError`。 —
`test_request_retries_after_401`、`test_request_retries_after_429`、
`test_request_404_not_found`、`test_request_403_access_error`、
`test_request_error_payload_extracted`、`test_request_rejects_unsafe_url`

## AC-8 SSO 桥接 hook 权限

`_set_microsoft_graph_tokens`：用户写本人凭证 OK；非 system 用户写他人 →
`AccessError`。 — `test_users_hook_self`、`test_users_hook_other_denied`

## AC-9 跳转目标安全

`_sanitize_post_auth_redirect`：单 `/` 开头站内路径通过；`//`、
`http://evil`、反斜杠 → `AccessError`。 — `test_post_auth_redirect_validation`

## AC-10 应用配置校验

`_graph_validate_configuration`：缺 tenant 或 client_id → `UserError`；
`_redirect_uri` 在缺 `web.base.url` 时 → `UserError`。 —
`test_application_configuration_validation`、`test_redirect_uri_requires_base_url`

## 运行方式

```bash
docker exec odoo odoo -c /etc/odoo/odoo.conf -d <db> \
  -i microsoft_graph --test-enable --test-tags /microsoft_graph \
  --stop-after-init --workers=0 --no-http
```

所有网络调用（token 端点、Graph API）全 mock，无网络、无真实凭证。
