# Microsoft Graph — 系统设计

## 定位

仓库分层模式（`llm` core+provider、`storage_backend_mcp` core+bridge）在
Microsoft 生态的对应物：本模块是 **auth 核心**，消费者（如
`storage_backend_sharepoint`）通过 m2o 引用应用注册并调用 service。

## 数据模型

```
microsoft.graph.application          # Entra 应用注册（server.env.mixin）
  ├─ name / graph_tenant_id / graph_client_id / graph_client_secret
  ├─ graph_scope / allow_user_authorization
  └─ credential_ids ──┐
                      ▼
microsoft.graph.credential           # 按（应用, 用户）的委托凭证
  ├─ application_id / user_id        # unique 约束
  ├─ entra_oid                       # Entra 身份绑定（一次绑定不可换）
  ├─ access_token / refresh_token / token_expiry / granted_scope
  └─ oauth_state / oauth_state_expiry / oauth_code_verifier / post_auth_redirect
```

凭证挂在应用而非消费者上：**一次授权 = 一个 (应用, 用户) 凭证**，同一应用的
多个消费者共享。这符合 Microsoft OAuth 的实际模型（按 app 注册 consent）。

## 关键取舍

### scope 放应用而非消费者

同一凭证下不同消费者要不同 scope 无法干净实现（刷新时按 app 的 scope 集
签发）。取舍：scope 集中在应用上；需要不同权限集（如一个只读、一个可写）
的场景建两个应用注册。消费者侧的写保护（如 sharepoint 的 read_only）仍在
消费者层额外把关。

### service 是 AbstractModel 而非 component

认证不是多态的（一个 Entra OAuth 协议），没有 per-provider 分派需求，无需
component 框架的 usage 查找。消费者 adapter 本身保持 component（storage.backend
的 `_usage` 机制不变），只是内部委托 `microsoft.graph.service`。

### post_auth_redirect

授权回调后回跳到发起页（消费者表单）。目标只在发起流程时由服务端写入并
校验：仅接受单个 `/` 开头的站内相对路径（拒 `//` 协议相对、带 scheme、
反斜杠），防开放重定向。回调时仅 group_system 用户使用该跳转，普通用户
固定跳 `/odoo`（与既有行为一致）。

### HTTP 语义（从 sharepoint v1 原样迁移）

- 401 → 强制刷新 token 重试一次；
- 429 → 按 `Retry-After`（上限 3 秒）重试一次；
- 404 → `FileNotFoundError`（Microsoft 可能以 404 掩盖无权限对象）；
- 403 → `AccessError`；
- 其余非 2xx → `UserError`，错误消息从 Graph JSON `error` 负载提取；
- 分页/上传等续链 URL 只接受 https 且 host 为 `graph.microsoft.com`。

### server_environment

应用注册继承 `server.env.mixin`，`_server_env_fields` 覆盖五个配置字段，
secret 等可由 ini 提供（与 `storage.backend` 同机制）。

## 扩展点（消费者接入清单）

1. manifest `depends` 加 `microsoft_graph`；
2. 消费者模型加 m2o `microsoft.graph.application`（`ondelete="restrict"`）；
3. 调用 `env["microsoft.graph.service"]._request(app, method, path, ...)`，
   需要指定用户时传 `user=`（后台任务应 `with_user(原用户)`）；
4. 发起授权：`_authorization_action(app, redirect_to="/web#...")`，或把用户
   导向 `/microsoft_graph/connect/<app_id>`（受 `allow_user_authorization` 门控）；
5. SSO 集成：`res.users._set_microsoft_graph_tokens(app, ...)`。

## 被否决的方案

| 方案 | 否决理由 |
|---|---|
| 配置留在消费者（backend）上，service 参数化传 dict | 凭证被迫按消费者隔离，同一用户对每个消费者重复授权；auth 模块无法独立成注册中心，未来消费者各自复制配置字段。 |
| 凭证按 (消费者, 用户) 存，token 复制多份 | 刷新要在多处同步；一个 refresh token 只能换一个 access token，多副本天然竞态。 |
| component 实现 service | 无多态需求，空转抽象；消费者 adapter 已是 component，不冲突。 |
| 回调后统一跳应用表单（不存 redirect） | 从 sharepoint backend 按钮发起授权后落到别的表单，UX 断裂。 |
| token 用 keychain/加密列存储 | 引入新依赖；Odoo 内置 Microsoft 凭证也是明文列 + 依赖数据库级防护，保持同一安全模型（见 README 安全说明）。 |
