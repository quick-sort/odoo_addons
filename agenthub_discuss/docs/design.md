# agenthub_discuss — 设计

## 触发点

继承 `discuss.channel._message_post_after_hook`。在消息落库后：

1. 只处理 `message_type` 为 `comment` / `email` 的消息。
2. 查找 `discuss_channel_id = channel.id` 且 `state = active` 的 `agenthub.thread`。
3. 跳过 author 为 agent service user partner 或 OdooBot 的消息。
4. 用 `author.user_ids[:1]` 解析 Odoo 用户；没有用户则跳过。
5. `html2plaintext` 取出纯文本，写 `agenthub.publish._enqueue`。

## 事件

- `event_type=message.created`
- `source=odoo`
- `route.thread_key=discuss.channel:<id>`，带 `agent_id`、`user_id`
- `meta.origin=odoo`，`meta.origin_record_id=mail.message,<id>`
- `event_id=odoo:mail.message:<id>:message.created`（幂等）

`agenthub.publish._enqueue` 在事务提交后尝试立即推送；失败由 publish cron 重试。

## 边界

- 不做 agent 回复投影；那由 `agenthub.recorder` 处理。
- 不修改 `discuss.channel` 的成员/权限。
- 失败只记录日志，不回滚用户已发的消息。
