# Microsoft Graph — 开发约束（自动加载）

设计文档见 `docs/`，这是唯一要求来源，改代码前先读：

- `docs/requirements.md` — 业务需求与边界
- `docs/design.md` — 数据模型、HTTP 语义、消费者扩展点
- `docs/acceptance.md` — 验收标准（QC 唯一依据）

红线：

1. **只用委托权限**：不做 client-credentials（应用权限）流，请求始终以当前
   Odoo 用户的身份发出。
2. **token 不出 NO_ACCESS 字段**：access/refresh token 与 OAuth 流程状态字段
   保持 `groups=fields.NO_ACCESS`，任何视图/接口不得暴露。
3. **凭证键为 (application, user)**：消费者扩展不另建凭证表，scope 属于应用
   而非消费者。
