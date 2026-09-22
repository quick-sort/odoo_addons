# agenthub_wecom — 系统设计

## 定位

`agenthub` 的第一个 channel 实现：企业微信智能机器人（aibot）**WebSocket
服务端**。对端是外部 agent 运行时装的企微插件（`@wecom/aibot-node-sdk`
客户端），主动 `ws://` 连进来，用 `bot_id + secret` 认证，之后双方用 JSON
文本帧通信。

本 addon **只做传输**：收发帧、管连接、归一化成 `mail.message`。对端是
哪个 agent（OpenClaw / OpenCode / …）它不关心——channel 只认 `bot_id`。

## 数据模型

继承 core 的 `agenthub.channel`，追加本 channel 的配置：

- `channel_type`：`selection_add=[("wecom", "企业微信")]`
- `bot_id`：Char，企微机器人 ID（subscribe 认证用）
- `secret`：Char，机器人 secret（subscribe 认证用）
- 健康字段复用 core（`last_run_at` / `error_count` / `last_error`）

一个 `agenthub.channel`（wecom）记录代表一个可被连接的 bot 端点；连接起来后
对端 peer 的 `bot_id` 与 `thread.peer_ref` 对应。

## 线上协议

WebSocket，文本帧，统一信封：

```json
{"cmd": "<command>", "headers": {"req_id": "<id>"}, "body": {...}}
```

ACK / 认证 / 心跳响应无 `cmd`，形如：

```json
{"headers": {"req_id": "<echo>"}, "errcode": 0, "errmsg": "ok"}
```

### 命令集（以 SDK 为准）

| 方向 | cmd | body 要点 |
|---|---|---|
| C→S | `aibot_subscribe` | `{bot_id, secret, scene?, plug_version?}` |
| C→S | `ping` | 无 body，`req_id` 以 `ping` 开头 |
| C→S | `aibot_respond_msg` | 被动回复：`{msgtype, stream:{id,finish,content}}` / `{msgtype:"text", text}` |
| C→S | `aibot_send_msg` | 主动发送：`{chatid, msgtype, ...}` |
| S→C | `aibot_msg_callback` | `{msgid, aibotid, chatid?, chattype, from:{userid}, msgtype, text/image/mixed/...}` |
| S→C | `aibot_event_callback` | `{msgid, msgtype:"event", event:{eventtype, ...}}` |

### 三条硬规则

1. **认证**：subscribe 回 `errcode:0` 即成功（`req_id` 回显，前缀
   `aibot_subscribe`）；非 0 客户端断连并按退避重试。secret 校验失败必须回非 0。
2. **心跳**：`ping` 回显 `req_id` + `errcode:0`；连续不回客户端判定连接死亡。
3. **ACK**：`aibot_respond_msg` / `aibot_send_msg` 每个都要按 `req_id` 精确
   回显 ACK，否则客户端 reject / 超时（默认 10s）。

### 入站 → mail.message 归一化

- 入站命令是 `aibot_respond_msg`（对端对 Odoo 推的「用户消息」的被动回复）与
  `aibot_send_msg`（对端主动发来的消息），都归一化成 inbound `mail.message`。
- `agenthub_external_id` = 帧的 `stream.id`（流式）或 `msgid`，缺省回退
  `headers.req_id`。
- `agenthub_reply_to_external_id` = 帧回传的 `req_id`（等于 Odoo 当初推
  `aibot_msg_callback` 时用的 `req_id`），用于 core/agent 关联回原 outbound。

`aibot_msg_callback` 是**出站**方向（Odoo 作为「用户」推消息给 bot），不在
入站归一化之列。

## 连接生命周期

### 承载：gevent worker

Odoo 的 WebSocket 只跑在 gevent worker（8072）。控制器：

- 路由 `@route('/wecom/aibot/ws', type='http', auth='public', websocket=True)`
- 握手成功后 `call_on_close` 进入连接循环（每个连接一个独立 handler 循环，
  `thread.type='websocket'`，被排除在请求限时之外）。

### 状态机

```
connect → 收 aibot_subscribe → 校验 secret
  ├─ 通过 → 注册 _live_connections[bot_id] → 回 errcode:0 → 进入消息循环
  └─ 失败 → 回 errcode:非0 → 断开（客户端会重试）
消息循环：收 ping 回 pong / 收 respond|send 回 ACK 并归一化入站 / 轮询出站
```

## 多连接处理

### 1. 按 bot_id 区分

gevent worker 进程内维护 `_live_connections: dict[bot_id, conn]`。不同 bot_id
的连接互不干扰。

### 2. 同 bot_id 互踢

新 `aibot_subscribe` 到来时，若 `bot_id` 已有连接：

1. 给旧连接推 `aibot_event_callback(eventtype=disconnected_event)`
2. 关旧 socket
3. 接管为新连接

复刻真实企微服务端行为；对端插件收到 `disconnected_event` 会停自动重连，
避免双实例互踢死循环。

### 3. 跨进程下发走 DB

`_live_connections` 只在 gevent worker 进程内。HTTP/cron worker（另一进程）
要推消息给对端，只能落 `mail.message`（`agenthub_delivery_state=pending`），由
连接循环轮询本 channel 的 pending 投递：

- 出站查询：`agenthub_delivery_state=pending` 且所属 thread 的
  `channel_id = 本 channel`。
- 多 gevent worker 用 `SELECT … FOR UPDATE SKIP LOCKED` 抢占，保证只有持有
  该 bot 连接的那个 worker 投递。
- 投递成功置 `sent`，失败置 `failed`。

## 与 core 的接口

作为 `agenthub.channel` 的 `channel_type="wecom"` 实现：

- `agenthub.channel.wecom` component：`start()`（起连接循环）、`stop()`、
  `send(message)`（把 outbound 投递到对端）。
- 入站：帧 → 归一化 inbound `mail.message` → 交 core 路由。

## 被否决的方案

| 方案 | 否决理由 |
|---|---|
| 复用 `bus.WebsocketConnectionHandler` | 深度耦合 bus 通知协议（subscribe/poll/channels），不是通用 JSON 协议承载。 |
| 独立 WS 进程（`websockets` 库） | 多一个进程/端口/运维面；「在 Odoo 里做 addon」诉求下先用 gevent 承载。 |
| 在 channel 里记录对端 agent 身份 | 企微 aibot 协议没有「我是谁」字段，无法识别，也不该假设。 |
| 媒体上传/解密一并实现 | 先跑通文本链路，媒体独立成后续阶段，避免 MVP 过大。 |
