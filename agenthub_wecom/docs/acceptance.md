# agenthub_wecom — 验收标准（QC 唯一依据）

跑法：
`docker exec odoo odoo -c /etc/odoo/odoo.conf -d <test_db> -i agenthub_wecom --test-enable --test-tags /agenthub_wecom --stop-after-init --workers=0 --no-http`。

测试用 `websocket-client` 或直接构造帧经协议处理器验证，**不依赖真实企微后台
、不联网、无真实密钥**（secret 用测试值）。

## 1. 装载与注册

- [ ] **AC1** 模块干净装载：`-u agenthub_wecom` 退出码 0。
- [ ] **AC2** `agenthub.channel` 的 `channel_type` 出现 `wecom` 值，且
  `_inherit` 追加了 `bot_id` / `secret` 字段。

## 2. 协议处理器（帧级，脱离 socket 测试）

- [ ] **AC3** `aibot_subscribe`：secret 匹配回 `errcode:0` + 回显 `req_id`；
  secret 不匹配回非 0。
- [ ] **AC4** `ping` 回显 `req_id` + `errcode:0`。
- [ ] **AC5** `aibot_respond_msg` / `aibot_send_msg` 各回精确 `req_id` 的 ACK。
- [ ] **AC6** 出站「用户消息」能编码成 `aibot_msg_callback` 帧（含 `msgid` /
  `chattype` / `from.userid` / `msgtype` / `text.content`）。

## 3. 入站归一化

- [ ] **AC7** `aibot_respond_msg` / `aibot_send_msg` 归一化成 inbound
  `mail.message`：`agenthub_direction=in`、内容正确、`agenthub_external_id` 填
  `stream.id`（或 `msgid`）、`agenthub_reply_to_external_id` 填回传 `req_id`。

## 4. 多连接

- [ ] **AC8** 按 `bot_id` 区分：两个不同 bot_id 各自注册到独立连接槽。
- [ ] **AC9** 同 bot_id 互踢：新连接注册时，旧连接收到
  `aibot_event_callback(eventtype=disconnected_event)` 且旧 socket 被关闭。
- [ ] **AC10** 出站队列：`agenthub_delivery_state=pending` 的出站 `mail.message`
  可被按所属 thread 的 `channel_id` 查询到，投递成功置 `sent`。

## 5. 承载

- [ ] **AC11** 存在 `websocket=True` 的路由（`/wecom/aibot/ws`），握手逻辑
  返回 101 升级响应。

## 6. XML

- [ ] **AC12** 所有 view/security/data XML 过 `xml.dom.minidom`。

## 7. 不联网

- [ ] **AC13** 全部测试无网络、无真实密钥可过。
