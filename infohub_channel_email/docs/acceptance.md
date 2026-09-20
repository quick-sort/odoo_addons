# InfoHub Email Channel — 验收标准

## AC-1 渠道类型与字段

`email` 在 selection 中；`email_to` 字段存在。 — `test_email_is_a_selectable_channel_type`、`test_email_to_field_exists`

## AC-2 入站邮件建条目

真实 MIME 报文经 `message_process` 进入，建出 `infohub.item`，正文进 `content_text`。 — `test_inbound_email_creates_an_item`

## AC-3 中转留档

原始邮件存到 `infohub.email.message`（subject/from/state=processed）。 — `test_inbound_email_is_stored_on_the_relay`

## AC-4 按收件人路由

两个渠道各自一个收件箱，邮件路由到正确渠道；大小写不敏感；cc 也命中；未知收件人
留档为 error 不丢。 — `test_email_routed_to_channel_by_recipient`、`test_matching_is_case_insensitive`、`test_cc_recipient_also_matches`、`test_email_with_unknown_recipient_is_kept_unmatched`

## AC-5 池子无 chatter

`infohub.item` 不含 `message_ids`；中转模型含。 — `test_pool_item_carries_no_chatter`

## AC-6 来源匹配与 fetch 语义

来源按发件人匹配（匹配不上留空）；`fetch_news` 返回空（邮件不轮询）。 — `test_source_is_matched_from_sender_name`、`test_fetch_returns_nothing_for_email`

## AC-7 拆分开关与调度

`split_items` 存在且默认关；打开且 agent 已配时，入站邮件置 `queued`、建 queue_job、
暂不建 item。 — `test_split_channel_queues_instead_of_syncing`

## AC-8 agent 未配回退

`split_items` 开但 agent 未配 provider/model 时，回退为同步单条路径，不丢邮件。 — `test_split_without_configured_agent_falls_back`

## AC-9 拆分入库

agent 回 N 条时建 N 个 item，标题/正文正确，正文进 `content_text`。 — `test_job_splits_digest_into_items`

## AC-10 空结果回退

agent 回 0 条时退化为单条（整封邮件）。 — `test_job_falls_back_to_single_item_when_no_items`

## AC-11 错误留档

agent 报错或答案非法时，中转记录置 `error` 并带 `error_message`。 — `test_job_records_agent_error`、`test_job_records_malformed_answer`

## AC-12 幂等重放

同一封邮件重放不产生重复 item（靠 `external_id` 去重）。 — `test_job_reprocessing_is_idempotent`

## 运行方式

```bash
docker exec odoo odoo -c /etc/odoo/odoo.conf -d <db> \
  -i infohub_channel_email --test-enable --test-tags /infohub_channel_email \
  --stop-after-init --workers=0 --no-http
```
