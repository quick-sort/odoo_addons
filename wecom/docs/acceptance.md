# 验收标准（acceptance）

QC 唯一依据。所有用例离线可跑：wechatpy client 全 mock，不联网、无需真实凭证。

## AC1 发送（既有，`tests/test_message_send.py`）

- [x] AC1.1 news 10 篇 → 按 8 篇分 2 批（8+2），各调一次 `message/send`，state=`sent`
- [x] AC1.2 news 1 篇 → 只发 1 次
- [x] AC1.3 textcard → 走 `send_text_card`，不走 `send_articles`
- [x] AC1.4 mpnews → 每篇上传一次封面图素材
- [x] AC1.5 news 无文章 → ValidationError
- [x] AC1.6 `send_message()` 传 articles → 自动创建文章子记录并发送

## AC2 msgid 记录（`tests/test_message_recall.py`）

- [ ] AC2.1 单条发送（textcard）成功 → `msgid` 字段 == 响应中的 `msgid`
- [ ] AC2.2 多批发送（news 10 篇）成功 → `msgid` 字段含两批共 2 个 msgid（每行一个）
- [ ] AC2.3 发送失败 → `msgid` 为空，state=`failed`

## AC3 消息撤回（`tests/test_message_recall.py`）

- [ ] AC3.1 已发送且 24h 内撤回 → 每个 msgid 各调一次 `POST message/recall`，
      state=`recalled`，`recall_date` 非空
- [ ] AC3.2 发送超过 24 小时 → 抛 UserError，**不调**撤回接口，state 不变
- [ ] AC3.3 撤回接口报错（errcode≠0 抛 WeChatClientException）→ state 仍为 `sent`，
      错误信息写入 `result` 且在事务回滚后仍可见（经独立游标落库；
      用例 `TestWecomRecallFailureBookkeeping`：TransactionCase 里测试事务的行
      对独立游标不可见，用例须用独立游标创建并发送记录使其真实提交）
- [ ] AC3.4 非 `sent` 状态（草稿）点撤回 → UserError，不调接口

## AC4 模块装载

- [ ] `-u wecom --stop-after-init` 退出码 0（含视图/权限/新字段装载）
- [ ] 改动的 XML 通过 well-formed 校验
