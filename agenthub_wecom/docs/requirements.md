# agenthub_wecom — 业务需求与边界

## 背景

外部 AI Agent 运行时（OpenClaw、OpenCode 等）要接入 Odoo，可以通过它们各自的
企业微信插件，把 `websocketUrl` 指到 Odoo，用 `bot_id + secret` 认证，走企业
微信智能机器人（aibot）长连接协议。

Odoo 侧需要扮演这个协议的 **WebSocket 服务端**：让外部运行时连进来，双方用
JSON 文本帧收发消息。本 addon 就是 `agenthub` 的第一个 channel 实现——只做
「传输」，对端是哪个 agent 它不关心、也不该关心。

## 目标

1. 实现 aibot WebSocket 服务端：握手、`aibot_subscribe` 认证、`ping` 心跳、
   `aibot_respond_msg`/`aibot_send_msg` 的 ACK。
2. 收发消息：把 Odoo 的出站消息作为「用户消息」（`aibot_msg_callback`）推给
   对端；接收对端的回包（`aibot_respond_msg` / `aibot_send_msg`）归一化成
   inbound `mail.message`。
3. 多连接：按 `bot_id` 区分、同 `bot_id` 互踢、跨进程下发走 DB。
4. 作为 `agenthub.channel` 的一个 `channel_type` 实现，挂进 core 的路由。

## 范围

### 在范围内

- aibot 协议：subscribe / ping / respond / send 的收发与 ACK。
- 文本消息（`text`）、图文混排（`mixed`）的入站归一化。
- 连接注册表、互踢（`disconnected_event`）、DB 出站队列。
- gevent worker 承载（`websocket=True` 路由）。

### 明确不做（本阶段）

- **不实现媒体上传/下载/解密**（`aibot_upload_media_*`、`image.aeskey` 加密
  下载）。先跑通文本，媒体后续加。
- **不实现模板卡片**（`template_card` / `aibot_respond_update_msg`）。
- **不实现真实企微后台的 Agent 模式**（自建应用 HTTP 回调的 XML/AES 加解密、
  `qyapi.weixin.qq.com` API）。那是另一条协议，另开 addon。
- **不识别对端 agent 身份。** channel 只认 `bot_id`，不保存「这是 OpenClaw
  还是 OpenCode」。
- 不碰生产端口（8069/8072/5432 等），WS 只服务在 gevent worker。
