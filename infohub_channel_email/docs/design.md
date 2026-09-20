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

## 摘要拆分 agent

订阅 newsletter 一封邮件通常聚合多条新闻。默认仍把整封邮件合成一条 item；渠道打开
`split_items` 后，入站邮件交给 `infohub_email_splitter` agent 拆成多条 item。

- **agent**：`llm.agent`（code `infohub_email_splitter`），无 tool 的纯转换，
  provider/model 由管理员配置（同 `infohub_agent` 的 `infohub_tagger`）。
- **流程**：`message_new` → `_to_item()` 分发。`split_items` 开且 agent 已配 →
  置 `state=queued` 并 `with_delay(channel="root.infohub")` 派发
  `_job_split_and_ingest`；否则走同步单条路径 `_ingest_single`。
- **输入/输出**：agent 只收正文纯文本，返回 `{"items":[{title,summary,url}]}`；
  逐条经 `channel._ingest` 复用核心入库管线（过滤/去重/source 匹配/正文渲染）。
- **去重身份**：单条 `external_id = <message-id>`，拆分条目
  `external_id = "<message-id>#<index>"`，靠 `(channel, external_id)` 唯一约束幂等。
- **回退语义**：agent 未配 / 返回 0 条 / split 已关 → 退化为单条路径，不丢邮件；
  agent 报错或答案非法 → `state=error` 留档。

## 被否决的方案

| 方案 | 否决理由 |
|---|---|
| 所有 email 都拆 | 单条新闻邮件也会被 agent 处理；按渠道开关更可控。 |
| `message_new` 里同步调 agent | 会阻塞 fetchmail/SMTP 网关在一次 LLM 调用上；与打标 agent 一致走 queue_job。 |
| 给 `infohub.item` 加 `mail.thread` | chatter 表随新闻条数膨胀（见上）。 |
| 每个 newsletter 一个 alias | 来源一多 alias 爆炸；收件人匹配更简单。 |
| 邮件也走 cron 轮询 | 邮件是推送的，无"拉取"语义；fetchmail 已经负责拉。 |
