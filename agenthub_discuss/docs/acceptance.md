# agenthub_discuss — 验收标准

- [ ] **AC1** 安装后 clean load。
- [ ] **AC2** 绑定 thread 的 Discuss 用户消息生成一条 `agenthub.publish`，`event_type=message.created`。
- [ ] **AC3** 事件带 `route.thread_key=discuss.channel:<id>`、`agent_id`、`user_id`。
- [ ] **AC4** 事件带 `meta.origin=odoo`、`meta.origin_record_id=mail.message,<id>`。
- [ ] **AC5** agent service user 的回帖不生成 publish。
- [ ] **AC6** OdooBot 消息不生成 publish。
- [ ] **AC7** 未绑定 agenthub thread 的 Discuss 频道不生成 publish。
- [ ] **AC8** 同一 mail.message 重复触发时 `event_id` 幂等。
