# AgentHub Relay — v1 职责、状态机与接口（草案）

> 状态：草案，2026-11-01。评审后合并进 `design.md` / `acceptance.md`。
> 关联文档：`design.md`、`relay-message-envelope.md`。
> 实现骨架：`../../agenthub_relay/`（v1 内存版；Redis 持久化、企微 gateway、HA 待补）。

## 1. 定位与非目标

Relay 是 AgentHub 的**实时消息层**：终结连接、归一协议、解析路由、排队投递、维护会话运行状态、生产归档事件。它不是长期存储、不是 UI、不是权限源，也不运行 agent。

| 角色 | 负责 | 不负责 |
|---|---|---|
| **Odoo** | Discuss UI、agent service user、配置（agent/identity/binding）、记录与归档、审计查询 | 实时队列、agent 路由、流式转发 |
| **Relay** | 实时路由、agent/渠道连接、inbox/outbox、租约与重试、presence、背压、durable log | 长期存储、UI、权限模型、agent 执行 |
| **agent-box** | 按 `thread_key` 维护 session、消费 turn、流式回包、心跳 | 跨 agent 路由 |
| **Odoo recorder** | 从 relay 拉取事件、批量幂等写 `mail.message`、Discuss 投影、归档 | 投递决策 |

非目标：

- 不做 exactly-once；只做 at-least-once + 幂等。
- 不做语义路由/意图识别；路由只按显式 identity/binding/thread。
- 不做长期附件存储；附件走对象存储，消息只带引用。
- 不直接操作 Discuss UI；投影由 Odoo recorder 完成。

## 2. 组件划分

| 组件 | 输入 | 输出 |
|---|---|---|
| `agent_gateway` | agent WebSocket / 长轮询 | 认证、presence、领取/回包/ack |
| `channel_gateway` | 企微 aibot WS 等 | 归一化入站 envelope、消费 outbox 发送 |
| `router` | inbound envelope、配置缓存 | 解析 identity/binding/agent/thread，创建 turn，写 agent inbox |
| `delivery` | agent inbox、channel outbox | 租约、重试、ack、DLQ |
| `state` | 各组件状态 | turn/delivery/presence/thread 活跃态（Redis） |
| `record_feed` | 所有语义事件 | 供 Odoo recorder 拉取的 `record` 流 |
| `config_sync` | Odoo 配置快照 | 原子替换路由缓存、token hash、渠道凭据 |
| `admin` | 运维请求 | 健康、指标、队列、DLQ、重放、强制下线 |

## 3. 队列与状态存储

v1 假设 **Redis Streams + Redis KV**；NATS JetStream 可作为等价替代。

| 名称 | 类型 | 用途 | 保留 |
|---|---|---|---|
| `agenthub.inbound` | Stream | 渠道/Odoo 入站 | 7 天 |
| `agenthub.agent.<id>.inbox` | Stream | 每 agent 收件箱 | 7 天 |
| `agenthub.agent.<id>.events` | Stream | agent 流式/ack 事件 | 7 天 |
| `agenthub.channel.<id>.outbox` | Stream | 待发往用户 | 7 天 |
| `agenthub.record` | Stream | 给 Odoo recorder | 7 天（按 lag 告警） |
| `agenthub.dlq` | Stream | 毒消息/超限投递 | 30 天 |
| `state:turn:<id>` | Hash | turn 状态、活跃 thread 锁 | TTL |
| `state:delivery:<id>` | Hash | 租约、attempt、状态 | TTL |
| `state:presence:<agent_id>` | Hash | 在线状态、last_seen、容量 | TTL |
| `lease:channel:<id>` | String | 渠道 socket 归属实例 | TTL + 续约 |

原则：

- **已接受的消息不能静默丢失**。队列满时对新入站施加背压（429/503），而不是丢旧消息。
- `record` 流落后超过阈值时告警，并对入口限流。
- Agent/channel 连接本身不持久化；重连后从 stream 游标恢复。

## 4. 状态机

### 4.1 Turn

| 当前 | 事件 | 下一状态 | 动作 |
|---|---|---|---|
| — | 入站消息/命令被接受 | `queued` | 创建 turn，写 agent inbox |
| `queued` | agent 领取 | `running` | delivery 置 `claimed` |
| `running` | 收到 final + ack | `completed` | 创建 outbox、写 record |
| `running` | 不可重试错误 / 超过最大尝试 | `failed` | 写 record、通知 Odoo |
| `queued` / `running` | 用户/系统取消 | `cancelled` | 丢弃未投递项、写 record |
| `queued` | 超过 deadline | `expired` | 写 record、通知 Odoo |

同一 `thread_key` 只允许一个非终态 turn；后续消息进入 thread backlog，按 FIFO 处理。

### 4.2 Agent delivery

| 当前 | 事件 | 下一状态 | 动作 |
|---|---|---|---|
| — | 入队 | `queued` | 写 delivery |
| `queued` | claim | `claimed` | 设置 `lease_until`、`attempt+1` |
| `claimed` | 首帧 stream / turn.started | `running` | 更新 presence=busy |
| `claimed` / `running` | ack `done` | `done` | 释放并发位、更新 presence |
| `claimed` / `running` | ack `failed`（可重试） | `queued` | 退避后重新入队 |
| `claimed` / `running` | 不可重试错误 | `failed` | 写 record |
| `claimed` / `running` | 租约过期 | `queued` | `attempt+1`；超过上限进 DLQ |
| `queued` | 超过 TTL | `failed` | 写 record、通知 owner |

### 4.3 Channel outbox

| 当前 | 事件 | 下一状态 | 动作 |
|---|---|---|---|
| — | 创建 | `pending` | 写 outbox |
| `pending` | gateway 领取 | `sending` | 设置租约 |
| `sending` | 发送成功 | `sent` | 写 record |
| `sending` | 发送失败（可重试） | `pending` | 退避重试 |
| `sending` | 超过上限 | `dead` | 进 DLQ、告警 |

### 4.4 Presence

| 当前 | 事件 | 下一状态 |
|---|---|---|
| — | WS 连接/认证 | `connecting` |
| `connecting` | 认证成功 | `online` |
| `online` | 领取 turn | `busy` |
| `busy` | turn 完成 | `online` |
| `online` / `busy` | 主动下线 | `draining` |
| `draining` | 无在途任务 | `offline` |
| 任意 | 心跳超时 | `offline` |

### 4.5 Thread 串行

- `state:turn:active:<thread_key>` 保存当前活跃 `turn_id` 和 owner 实例。
- 新 turn 到达时若已有活跃 turn，进入 backlog；活跃 turn 终止后由同一实例或接管实例取下一个。
- 锁带 TTL，实例崩溃后由其他实例接管。

## 5. 接口

### 5.1 Agent WebSocket

端点：`wss://relay/v1/agent/ws`

```json
// 客户端首帧
{
  "type": "auth",
  "agent_id": 12,
  "token": "…",
  "client_version": "agent-box/0.1.4",
  "last_event_id": "evt_…"
}
```

```json
// 服务端
{
  "type": "hello",
  "heartbeat_sec": 20,
  "resume_from": "evt_…",
  "limits": {"max_inflight": 4, "max_payload_bytes": 1048576}
}
```

```json
// 服务端投递
{
  "type": "deliver",
  "delivery_id": "dlv_…",
  "turn": {
    "turn_id": "turn_…",
    "thread_key": "thread:…",
    "state": "running"
  },
  "message": {
    "role": "user",
    "content": "帮我修一下 main.py",
    "body_json": null,
    "final": true
  },
  "history": []
}
```

```json
// agent 流式回包
{
  "type": "stream",
  "delivery_id": "dlv_…",
  "turn_id": "turn_…",
  "stream_id": "stream_…",
  "seq": 1,
  "role": "assistant",
  "content": "先看一下文件…",
  "body_json": null,
  "final": false
}
```

```json
// agent 确认
{
  "type": "ack",
  "delivery_id": "dlv_…",
  "turn_id": "turn_…",
  "state": "done",
  "error": null
}
```

- 心跳：WS ping/pong 或 `{"type":"ping"}` / `{"type":"pong"}`。
- 恢复：`last_event_id` / `resume_from`；无法恢复时返回 `RESYNC_REQUIRED`，由 relay 发送当前队列快照。
- 关闭码：`4001` 认证失败、`4003` 越权、`4008` 协议错误、`1013` 过载重试。
- HTTP 降级（可选）：`POST /v1/agent/claim`、`POST /v1/agent/stream`、`POST /v1/agent/ack`、`POST /v1/agent/heartbeat`。

### 5.2 Odoo → Relay 发布

用于 Discuss 入站消息、cron 命令、配置失效通知。

```
POST /v1/publish
Headers:
  X-AgentHub-Timestamp: 1760000000
  X-AgentHub-Signature: HMAC-SHA256(secret, timestamp + "." + body)
Body: <envelope>
Response: {"status": "accepted" | "duplicate", "event_id": "…"}
```

- Odoo 在同一个事务里写 `agenthub.publish` outbox，再由 worker 推送；失败重试。
- Relay 按 `event_id` 幂等；重复返回 `duplicate`。
- 错误：400 非法 envelope、401 签名失败、429 限流、503 过载。

### 5.3 Relay → Odoo record feed

Odoo recorder 主动拉取，自己维护 checkpoint：

```
Headers: X-AgentHub-Recorder-Token: <token>

GET /v1/record?cursor=<opaque>&limit=500
Response:
{
  "events": [<envelope>, ...],
  "next_cursor": "…",
  "lag_seconds": 1.2
}

POST /v1/record/ack
{"cursor": "…"}
```

Odoo 侧配置：`agenthub.relay_url`、`agenthub.relay_recorder_token`、`agenthub.recorder_batch_limit`。recorder 由 `agenthub.record.cursor._cron_pull()` 每分钟拉取一次；<5 秒 SLO 需要后续长轮询/推送 worker。

- Odoo recorder 先批量幂等写库，再提交 cursor；cursor 存在 Odoo。
- Relay 用 ack cursor 计算 lag 并决定保留/限流。
- 默认只要求 recorder 落 `message.final`；`message.updated` 可忽略或用于流式 UI。

### 5.4 配置同步

Relay 从 Odoo 拉取版本化快照：

```
Headers: X-AgentHub-Config-Token: <token>

GET {odoo}/agenthub/relay/config?version=<current>
Response:
{
  "version": 43,
  "agents": [
    {"id": 12, "token_hash": "…", "active": true}
  ],
  "channels": [
    {"id": 34, "type": "wecom", "active": true,
     "bot_id": "…", "secret": "…"}
  ],
  "identities": [
    {"channel_id": 34, "peer_ref": "zhangsan", "user_id": 56}
  ],
  "bindings": [
    {"user_id": 56, "channel_id": 34, "agent_id": 12}
  ]
}
```

Odoo 侧配置 `agenthub.relay_config_token`；relay 侧用 `AGENTHUB_ODOO_CONFIG_URL`、`AGENTHUB_ODOO_CONFIG_TOKEN` 和 `AGENTHUB_CONFIG_POLL_SECONDS` 拉取。

- Odoo 是唯一配置源；relay 原子替换缓存。
- 轮询间隔 10–30s；Odoo 可在事务提交后调用 `POST /v1/config/reload` 加速。
- 渠道密钥：`secret_ref` 指向 relay secret store，或随快照经 TLS/mTLS 下发；不写日志。
- 外部渠道的 `thread_key` 由 relay 确定性生成：`agenthub:channel:<channel_id>:peer:<peer_ref>:agent:<agent_id>`；Odoo recorder 据此 ensure thread。Discuss 的 `thread_key` 由 Odoo 在 publish 事件中直接给出。

### 5.5 企微 channel gateway

复用 `agenthub_wecom` 已实现的 aibot 协议（认证、ping、`req_id` ACK、消息回调）。

- 每个 `bot_id` 在 Redis 抢 `lease:channel:<id>`，只有租约持有者建立 WS；心跳续约，过期后其他实例接管。
  - 同实例内同一 bot 重连：踢旧连接（推 `disconnected_event` 后关闭），保持 legacy 行为。
  - 跨实例重复订阅：直接回非 0 errcode 拒绝，不互踢；等租约 TTL 过期后由新实例接管。
- 入站回调统一转成 `message.updated` / `message.final` envelope，交给 router。
  - 出站 callback 的 `req_id` 在 Redis 记录 `req_id → thread_key/agent_id/turn_id` 映射，
    机器人回包按 `req_id` 找回原 turn。
  - 回包 envelope 带 `meta.origin=channel`：状态机只记录、**不再生成 outbox**，
    避免把机器人已经发回用户的消息再回灌一遍形成回声环。
- 出站消费 `agenthub.channel.<id>.outbox`，发送成功后 ack；发送前写入 `req_id` 映射。
- 企微媒体上传/下载由 gateway 完成，附件只传引用（v1 仅文本）。

### 5.6 Admin API

| 端点 | 用途 |
|---|---|
| `GET /healthz` | 存活/就绪 |
| `GET /metrics` | Prometheus |
| `GET /v1/admin/agents` | presence、队列深度、连接数 |
| `GET /v1/admin/queues` | 各 stream 长度、lag |
| `GET /v1/admin/dlq` | 毒消息/超限投递 |
| `POST /v1/admin/dlq/replay` | 重放 |
| `POST /v1/admin/agents/{id}/disconnect` | 强制下线 |
| `POST /v1/admin/config/reload` | 立即拉配置 |

## 6. 关键流程

### 6.1 企微用户 → agent → 企微

1. Gateway 收到用户消息，生成 `message.created`（source=channel）。
2. Router 用 `peer_ref` 查 identity → user → binding → agent，生成确定性 `thread_key`。
3. 创建 turn，写入 `agent.<id>.inbox`；同时写 `record`。
4. Agent 领取、流式回包；relay 更新 turn 状态并写 `record`。
5. final 后创建 `channel.<id>.outbox`；gateway 发送、ack、写 `record`。
6. Odoo recorder 批量拉 `record`，落 `mail.message` / `agenthub.turn` / `agenthub.delivery`。

### 6.2 Discuss 用户 → agent → Discuss

1. Odoo 在绑定的 `discuss.channel` 里检测到用户消息，写 `agenthub.publish` outbox。
2. Odoo worker 调 `POST /v1/publish`，事件带 `thread_key=discuss.channel:<id>` 与 `agent_id`；同时带 `meta.origin=odoo`、`meta.origin_record_id=mail.message,<id>`，供 recorder 去重。
3. Relay 直接入 agent inbox，不做二次路由。
4. Agent 回包最终写 `record`；Odoo recorder 以 agent 的 service user 身份投影回 `discuss.channel`。用户原始消息已存在，recorder 按 `origin_record_id` 跳过，不重复创建。

### 6.3 cron/命令 → agent

1. Odoo 创建 `agenthub.command`，写 publish outbox。
2. Relay 生成 turn，投递给目标 agent。
3. Agent 回包按 `reply_mode`：`none` 只落库；`owner` 通知 owner；`thread` 回到指定 thread。

### 6.4 流式

1. 首帧 `message.updated`（`final=false`）写入 relay 热日志；Odoo recorder 默认忽略。
2. 中间帧按 `seq` 更新同一 `stream_id`；relay 节流后转发。
3. `message.final` 收尾；生成 outbox；recorder 落一条 `mail.message`。
4. agent 崩溃/租约过期：未 ack 的 delivery 重投；agent 用 `(turn_id, stream_id, seq)` 幂等重放。

## 7. 错误码与重试

| 错误码 | 场景 | 处理 |
|---|---|---|
| `AUTH_FAILED` | token 错误/过期 | 关闭连接，4001 |
| `FORBIDDEN` | 越权领取其他 agent | 4003，记录审计 |
| `INVALID_ENVELOPE` | 字段缺失/校验失败 | 400，不重试 |
| `UNSUPPORTED_VERSION` | `event_version` 不支持 | 400 |
| `PAYLOAD_TOO_LARGE` | 内容/附件超限 | 400 |
| `AGENT_OFFLINE` | 投递时 agent 不在线 | 留在队列，TTL 后 expired |
| `AGENT_QUEUE_FULL` | 单 agent 队列超限 | 429/503，对新入站背压 |
| `THREAD_BUSY` | 同 thread 已有活跃 turn | 入 backlog |
| `TURN_NOT_FOUND` | 回包引用未知 turn | 拒绝并审计 |
| `DELIVERY_LEASE_EXPIRED` | 租约过期 | 重新入队，attempt+1 |
| `RESYNC_REQUIRED` | 断线游标过旧 | 发送队列快照 |
| `RATE_LIMITED` | 超频 | 429 + Retry-After |
| `INTERNAL` | 未知错误 | 503，退避重试 |

重试策略：

- 网络/5xx：指数退避，带 jitter。
- 业务错误（4xx 非 429）：不重试，进 DLQ/失败。
- Agent 明确标记不可重试：failed。
- 最大尝试次数按 agent/channel 可配；超过进 DLQ 并通知 Odoo。

## 8. 背压与限制

- 每 agent：最大排队 turn 数、最大未 ack 数、最大并发 turn、RPC 频率。
- 每 thread：backlog 上限。
- 每 channel：outbox 上限、发送速率。
- 全局：`record` lag 上限、stream 保留上限、单事件大小。
- 触发限制时优先拒绝**新**入站（429/503），不丢已接受的消息；通过 control 事件通知 Odoo，Odoo 可回消息给用户。

## 9. 安全

- 全链路 TLS；agent token 哈希存储、常量时间比较、可轮换。
- Agent 只能访问自身 inbox/events；route 中的 `agent_id` 必须与 token 匹配。
- Odoo publisher 使用 HMAC + 时间戳，防重放。
- 配置快照包含 token hash/渠道密钥，必须经 mTLS 或等价通道传输。
- 附件类型/大小校验；不把密钥、token 写日志。
- Admin API 独立鉴权，默认只暴露内网。

## 10. 多实例与 HA

- **Agent 连接**：可落在任意实例；presence 写 Redis；断线可重连到其他实例，从 stream 游标恢复。
- **渠道 socket**：按 `bot_id` 租约独占；实例故障后租约过期，其他实例接管。
- **Router**：按 `thread_key` 分片，保证同 thread 顺序；v1 可单实例。
- **Record feed**：共享 stream；Odoo recorder 从任意实例拉取。
- **配置**：版本化快照原子替换；旧版本请求可继续服务直到新版本就绪。

## 11. 可观测性

指标：

- 在线 agent 数、连接数、WS 重连次数
- 每 agent/每 channel 队列深度
- 投递延迟 p50/p95/p99、ack 延迟
- 租约过期率、DLQ 大小
- `record` lag（秒/条）
- 发送失败率、限流次数
- turn 成功率/失败率

日志：结构化，带 `event_id`、`turn_id`、`thread_key`、`agent_id`。
追踪：可选 OpenTelemetry，跨 gateway → router → delivery → recorder。

## 12. v1 范围

包含：

- 单 relay 实例（可 1 active + 1 standby）
- Redis Streams + Redis KV
- Agent WebSocket（含认证、心跳、投递、stream、ack、resume）
- 企微 aibot gateway（含 bot 租约）
- Router（identity/binding 解析、确定性 thread_key、thread 串行）
- 配置同步（版本化拉取）
- Odoo publish / record feed 接口
- Odoo recorder：拉取 record feed、幂等写 `mail.message`、Discuss 投影
- 租约、ack、幂等、DLQ（人工重放）
- 基础 metrics/health/admin

不包含：

- 多实例 router 分片（后续）
- Discuss 流式中间态投影（后续）
- 图形化 DLQ/replay（后续）
- NATS/多机房/跨区
- 语义路由/LLM 分类

## 13. 待定项

- Redis Streams vs NATS JetStream 的最终选型（v1 假设 Redis）。
- Odoo 配置推送 vs relay 轮询的最终组合。
- 渠道密钥放 relay secret store 还是随配置快照下发。
- Discuss 是否需要流式中间态展示。
- `agenthub.command` 的 payload schema 是否按命令名注册。
- `thread_key` 的最终格式与 Odoo 侧解析规则。
