# agenthub_discuss — 开发约束（自动加载）

设计文档见 `docs/`，这是唯一要求来源，改代码前先读：

- `docs/requirements.md` — 业务需求与边界
- `docs/design.md` — 架构与 hook 边界
- `docs/acceptance.md` — 验收标准

红线：

1. **只做入站发布，不做路由/投递。** 本 addon 只把 Discuss 用户消息写入
   `agenthub.publish`；路由、队列、agent 投递都在 relay。
2. **跳过回声。** agent service user partner、OdooBot 的消息不得回灌。
3. **Origin 去重。** 必须带 `meta.origin_record_id=mail.message,<id>`，recorder
   据此避免重复创建用户消息。
