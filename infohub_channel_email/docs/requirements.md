# InfoHub Email Channel — 业务需求

## 要解决的问题

让 InfoHub 能接收通过邮件订阅的 newsletter，解析后汇入池子。

## 范围

**做**：

- 提供 `email` 渠道类型
- 一个渠道对应一个收件邮箱（`email_to`）
- 入站邮件经 `mail.alias` 到达中转模型，解析成 `infohub.item`
- 按收件人地址把邮件路由到正确的渠道
- 原始邮件留档（改版后可重解析）

**不做**：

- 不发邮件、不做摘要推送
- 不做邮件正文的 LLM 解析/打标（那是 `infohub_agent` 的事）
- 不下载邮件附件

## 非功能要求

1. **池子保持干净**：`infohub.item` 不得带 chatter 三张表。
2. **路由健壮**：收件人匹配大小写不敏感，cc 也算；无匹配时留档不丢。
3. **离线可测**：用真实 MIME 报文走 `message_process`，无网络。
