# InfoHub Email Channel — 系统设计

## 中转模型：infohub.email.message

`mail.alias` 只能路由到继承 `mail.thread` 的模型（它的 `alias_model_id` domain
要求目标有 `message_ids`）。若让 `infohub.item` 直接继承 `mail.thread`，chatter
三张表（`mail_message`/`mail_followers`/`mail_notification`）会随新闻条数膨胀。

因此用一个**中转模型**接邮件：

- `infohub.email.message`：`_inherit = ["mail.thread"]`，`message_new` 里解析
  标题/正文/发件人/日期，转写成 `infohub.item`
- `infohub.item` 保持无 chatter
- 原始邮件留在中转记录上，改版后可重解析

## 路由：静态 alias + 收件人匹配

一个静态 `mail.alias`（`infohub`）收所有 newsletter，然后按 `channel.email_to`
匹配收件人决定归属。加一个 newsletter 不需要加 alias。

`_match_channel(recipients)` 把 `to`/`recipients`/`cc` 拼起来做大小写不敏感的子串
匹配；无匹配则 channel 留空、state=error，记录留在中转表供人工处理。

## 组件扩展

- `infohub.fetch.email`：返回 `({}, [])`——邮件是被推入的，不轮询
- `infohub.content.email`：`subject`/`source`（发件人）/`date` 从邮件 raw dict 取

## 被否决的方案

| 方案 | 否决理由 |
|---|---|
| 给 `infohub.item` 加 `mail.thread` | chatter 表随新闻条数膨胀（见上）。 |
| 每个 newsletter 一个 alias | 来源一多 alias 爆炸；收件人匹配更简单。 |
| 邮件也走 cron 轮询 | 邮件是推送的，无"拉取"语义；fetchmail 已经负责拉。 |
