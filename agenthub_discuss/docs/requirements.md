# agenthub_discuss — 业务需求与边界

## 背景

用户在 Discuss 里与 agent 的 service user partner 对话。Odoo 需要把这条用户消息
交给 relay 路由到对应 agent，但消息本身已经落在 `mail.message` 里。

## 目标

- 检测绑定到 `agenthub.thread` 的 Discuss 频道。
- 把用户消息写成 `agenthub.publish` 的 `message.created` 事件。
- 带 `meta.origin=odoo` 和 `meta.origin_record_id=mail.message,<id>`，供 recorder 去重。
- 跳过 agent 自己和 OdooBot 的消息，避免回声。

## 不做

- 不做路由、队列、agent 投递（relay）。
- 不处理附件/流式（后续）。
- 不创建 `agenthub.channel` 记录；Discuss-only thread 用 `discuss_channel_id`。
