# agenthub — 业务需求与边界

## 背景

Odoo 需要与外部 AI Agent 运行时（当前是 agent-box 实例）对话。对话的入口不唯一：

- 传输层（channel）：Discuss/Odoobot、企业微信 bot，未来还有 Web、Telegram、邮件等。
- Agent 层（agent）：一个用户可以有多个 agent-box 实例，各自有独立工作区、权限和运行环境。

目标规模是 **>100 个 agent、50 万条消息/天**。在这个量级上，如果让 Odoo 自己承载实时连接、路由和投递队列，会与 HTTP/gevent worker、ORM、Discuss 通知和数据库争抢资源。因此需要把实时消息层拆出来，Odoo 专注配置、UI、权限和长期记录。

## 目标

1. **Relay 作为实时消息层**：终结 agent/channel 连接、归一协议、按配置路由、排队投递、维护 presence 与背压、生产 durable 事件。
2. **Odoo 作为配置与归档中心**：Discuss UI、agent service user、identity/binding 配置、publish outbox、异步 recorder、`mail.message` 长期归档与审计。
3. **外部 agent-box 通过 relay 接入**：agent 是外部进程，以 Odoo service user 为身份；通过 WebSocket 连 relay，按会话维护 session，流式回包。
4. **消息模型对齐 `llm`**：最小记录单元是语义 message（user/assistant/tool/system），用 `mail.message` + role/subtype + body_json 表达；流式回复用占位消息原地更新，默认只落最终消息。
5. **多 agent 入口**：Discuss 里用户直接与 agent 的 service user partner 会话；企微等渠道通过 `(user, channel) → agent` 的 binding 配置。
6. **渠道隔离**：同一用户在 Discuss 与企微有各自独立的会话上下文；thread 以 `(channel, peer, agent)` 区分。

## 范围

### 在范围内

- **Odoo core / addon**
  - 模型：`agenthub.channel`、`agent`、`identity`、`binding`、`thread`、`turn`、`command`、`delivery`（审计副本）、`publish`（outbox）、`record.cursor`。
  - `mail.message` 扩展：`agenthub_role`、`agenthub_body_json`、`is_error`、`agenthub_content`、`turn/stream/external id` 等。
  - Discuss 入站发布、最终消息投影、cron 命令、agent/service user/token 管理、record rule。
  - 异步 recorder：从 relay 拉取事件，批量幂等写 `mail.message` / turn / delivery，并归档。
- **Relay（独立服务）**
  - agent WebSocket gateway（认证、心跳、投递、stream、ack、resume）。
  - 渠道 gateway（企微 aibot；每个 bot_id 单 owner 租约）。
  - Router（identity/binding 解析、确定性 thread_key、thread 串行）。
  - delivery/outbox（租约、重试、DLQ）、presence、背压、配置同步。
  - `record` 流与 Odoo recorder 拉取接口。
  - 基础 metrics/health/admin。
- **agent-box**
  - relay 客户端：`AGENT_ID` / `AGENT_TOKEN` / `RELAY_URL`；WS 或长轮询。
  - `thread_key ↔ session_id` 映射；流式回包带 `turn_id/stream_id/seq/final`。
- **cron/命令**
  - Odoo 定时任务可创建 `agenthub.command`，按 `reply_mode` 指定回复去向。

### 明确不做（本阶段）

- **目标架构中不再由 Odoo 持有企微 WS**。Odoo 内的 `agenthub_wecom` 仅作为 legacy 保留；同一 `bot_id` 不能同时由 Odoo 和 relay 持有。
- **不做语义路由/LLM 意图分类**。路由只按显式 identity/binding/thread；无法确定时拒绝并提示配置。
- **不承诺 exactly-once**。Relay 是 at-least-once，消费方用 `(turn_id, stream_id, seq)` 等键幂等。
- **Relay 不做长期存储**。长期归档在 Odoo；relay 只保留热日志（默认 7 天）。
- **不把所有流式帧写进 `mail.message`**。默认只记录最终语义消息；中间帧留在 relay 热日志。
- **v1 不做**：relay 多实例 router 分片、跨机房、Discuss 流式中间态投影、图形化 DLQ/replay、群聊完整语义。
- **不碰生产端口**。relay 与 Odoo 的部署边界按运维规范另行约定。

## 非功能约束

- **规模**：100+ agent、50 万消息/天；单 relay 实例 v1 目标，可水平扩展留到后续。
- **Odoo 不在热路径**：长连接、路由、队列、租约、重试都在 relay；Odoo 只做配置、Discuss UI、publish outbox、record feed/归档。
- **记录一致性**：默认异步 recorder，lag SLO < 5 秒；若要求投递前可查，只对用户消息改为同步写前记录。
- **可靠性**：已接受的消息不能静默丢失；relay 重启可恢复；DLQ 可人工重放。
- **安全**：agent token 哈希存储、按 agent 隔离 inbox；Odoo publish 用 HMAC；渠道密钥不落日志；Odoo 权限不被 relay 绕过。
- **可观测**：每 agent/channel 队列深度、投递延迟、租约过期率、DLQ、record lag、WS 重连。
- **测试**：Odoo 测试无网络/无 API key；relay 使用 fake channel/agent；集成测试使用 fake relay。

## 关键术语

- **channel**：面向用户的传输（Discuss、企微等）。
- **agent**：一个外部 agent-box 实例；在 Odoo 里有唯一的 service user/partner。
- **thread**：`(channel, peer, agent)` 的一段会话；渠道隔离。
- **turn**：一次提问/命令 → agent 执行 → 回复。
- **relay**：实时消息层，持有连接、路由、队列和 durable log。
- **recorder**：Odoo 侧消费者，从 relay 拉事件并批量归档。
