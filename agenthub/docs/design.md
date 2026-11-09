# agenthub — 系统设计

## 总览：两轴正交，relay 中转，Odoo 归档

agenthub 把「Odoo 与外部智能对话」拆成两个正交维度：

- **channel（传输）**：消息从哪条线到达用户。Discuss/Odoobot、企微 bot、未来 Web 等。
- **agent（应答）**：一个外部 agent-box 实例，负责理解消息并回复。一个用户可以有多个 agent。

两者互不依赖，由数据在运行时绑定：一个会话（channel + peer + agent）由 `agenthub.thread` 表达。channel addon 与 agent addon 都只依赖 core。

**目标部署形态（>100 agent）**：

```
用户
 ├─ Discuss（Odoo 原生 UI）── Odoo publish outbox ──┐
 └─ 企微 / 其他渠道 ── relay channel gateway ────────┤
                                                    ▼
                                                 Relay
                          ┌─────────────────────────┼─────────────────────────┐
                          ▼                         ▼                         ▼
                   agent inboxes            channel outboxes           record stream
                          │                         │                         │
                    agent-box × N            渠道发送                   Odoo recorder
                                                                             │
                                                                             ▼
                                                               mail.message / turn / delivery
```

- **Relay**：实时消息层。终结 agent/渠道连接、归一协议、解析路由、排队投递、维护 presence/背压、生产 durable 事件。
- **Odoo**：Discuss UI、agent service user、配置（agent/identity/binding）、publish outbox、异步 recorder、归档与审计。
- **agent-box**：外部进程。通过 WebSocket 连 relay，按 `thread_key` 维护 session，流式回包。

**Odoo 不在实时热路径**：长连接、路由和队列都在 relay。Odoo 只做配置、Discuss UI、事件发布、异步记录与归档。Discuss 是 Odoo 原生入口，它的入站消息由 Odoo 写入 publish outbox，但不做路由。

运行时的操作事实来源是 relay 的 durable log；Odoo 是可查询的长期归档。recorder lag 目标 SLO < 5 秒；当前 v1 骨架用 1 分钟 cron 拉取，达到 5 秒需要后续长轮询/推送 worker。

## 数据模型

所有模型在 `agenthub` core，namespace 为 `agenthub.*`，另加 `mail.message` 扩展。

| 模型 | 作用 |
|---|---|
| `agenthub.channel` | 用户侧传输配置 |
| `agenthub.agent` | 外部 agent-box 实例注册 |
| `agenthub.identity` | 渠道外身份 ↔ Odoo 用户 |
| `agenthub.binding` | 用户配置：哪个渠道找哪个 agent |
| `agenthub.thread` | 会话（channel + peer + agent） |
| `agenthub.turn` | 一次提问 → 执行 → 回复 |
| `agenthub.command` | cron/系统下发命令 |
| `agenthub.delivery` | 投递审计副本；热队列在 relay |
| `agenthub.publish` | Odoo → relay 的发布 outbox |
| `agenthub.record.cursor` | Odoo recorder 的 checkpoint |

### agenthub.channel

继承 `collection.base`。字段：

- `channel_type`：Selection，**core 置空**，由各 channel addon `selection_add` 填充。
- `name`、`active`、健康状态（`last_run_at` / `error_count` / `last_error`）。
- 渠道专属字段由各 addon `_inherit` 追加（企微的 `bot_id`/`secret` 等）。
- 目标架构下，外部渠道的 socket 由 relay gateway 持有；Odoo 只保存配置，并把凭据/引用同步给 relay。

Discuss 作为 Odoo 原生渠道，不强制创建 `agenthub.channel`：`agenthub.thread.channel_id` 可为空，用 `discuss_channel_id` 关联真实的 `discuss.channel`。`agenthub_discuss` 负责在 `_message_post_after_hook` 里把用户消息写入 publish outbox。

### agenthub.agent

继承 `collection.base`。一个记录代表一个外部 agent-box 实例；同一个用户可有多条。

- `name`、`agent_type`、`active`
- `runtime`：`relay`（外部 agent-box）或 `in_process`（Odoo 内适配器，如 `llm.agent`/人工）。
- `owner_user_id`：授权人、权限天花板（可选）。
- `user_id`：执行身份/专职 service user（required；内部用户、active）。**每个 agent 一个唯一 service user**，它在 Discuss 里的 partner 就是用户直接选择的对话对象。
- `partner_id`：related `user_id.partner_id`，用于 Discuss 显示与消息作者。
- `token_hash`：relay 认证 token 的哈希；明文只在生成时展示一次。
- `state` / `last_seen`：从 relay presence 同步，仅展示，不作为投递依据。
- `workspace` / `project` 等 JSON 元数据，描述 agent-box 的运行环境。
- `api_key`：legacy 字段，保留兼容；新实现使用 `token_hash`。

约束：

- `user_id` 必须是内部用户（`share=False`）且 `active=True`。
- 活跃 agent 的 `user_id` 唯一；不允许两个 agent 共用同一个 service user，否则 Discuss 无法区分。
- 允许 `user_id == owner_user_id`（以 owner 本人身份执行），但推荐专职 service user。

### agenthub.identity

渠道外身份映射：

- `channel_id`、`peer_ref`（企微 `userid`、外部会话 id 等）
- `partner_id` / `user_id`
- `active`
- 唯一约束 `(channel_id, peer_ref)`

没有 identity 就无法把渠道消息映射到用户，也就无法应用“用户各自的配置”。

### agenthub.binding

用户侧路由配置，主要用于非 Discuss 渠道：

- `user_id`、`channel_id`、`agent_id`
- `active`
- 唯一约束 `(user_id, channel_id)`（v1：同一用户在同一渠道绑定一个 agent）

Discuss 不走 binding：用户直接与 agent 的 service user partner 会话，partner 即路由键。

### agenthub.thread

继承 `mail.thread`。会话载体：

- `name`、`channel_id`（外部渠道；Discuss-only 可为空）、`peer_ref`、`agent_id`
- `external_id`：渠道侧稳定标识
- `relay_thread_key`：relay 使用的稳定键（唯一/索引）
- `discuss_channel_id`：Discuss 场景关联的真实 `discuss.channel`
- `state`：`active` / `closed`
- 约束：`channel_id` 或 `discuss_channel_id` 至少一个；`(channel_id, peer_ref, agent_id)` 唯一；`relay_thread_key` 唯一（Discuss 去重靠它）

`relay_thread_key`：

- 外部渠道：`agenthub:channel:<channel_id>:peer:<peer_ref>:agent:<agent_id>`（确定性生成）
- Discuss：`discuss.channel:<id>`（由 Odoo publish 事件直接给出）
- 命令：`command:<id>`

外部渠道的确定性 thread_key 让 relay 不需要查询 Odoo 的 thread 表；Odoo recorder 在归档时 ensure thread。

### agenthub.turn

一次「提问/命令 → agent 执行 → 回复」的聚合：

- `thread_id`、`agent_id`、`inbound_message_id`
- `relay_turn_id`：全局唯一，用于幂等
- `state`：`queued` / `running` / `completed` / `failed` / `cancelled` / `expired`
- `attempt`、`started_at`、`finished_at`、`error`
- `is_active`：布尔标记；同一 thread 只允许一个活跃 turn（实现用部分唯一索引）

### agenthub.command

cron/系统下发命令：

- `agent_id`、`thread_id`（可选）
- `name`、`payload`（Json）
- `reply_mode`：`none` / `owner` / `thread`
- `state`、`result_message_id`、`created_by`
- 定时任务通过 `ir.cron` 创建 command，再由 publish outbox 发给 relay。

### agenthub.delivery

**只作为 Odoo 侧审计副本**，由 recorder 写入；不是热队列：

- `turn_id`、`message_id`、`agent_id`/`channel_id`
- `leg`：`to_agent` / `to_user`
- `relay_delivery_id`、`state`、`attempt`、`error`
- `created_at`、`sent_at`

热队列、租约、重试和 DLQ 都在 relay；Odoo 不轮询 `pending` 消息。

### agenthub.publish / agenthub.record.cursor

- `agenthub.publish`：Odoo → relay 的 outbox。与业务消息/命令在同一事务写入，由 worker 推送；relay 按 `event_id` 去重。
- `agenthub.record.cursor`：Odoo recorder 拉取 relay `record` 流的 checkpoint。recorder 先批量幂等写库，再提交 cursor。

### agenthub.recorder（Odoo 消费端）

- AbstractModel；`_process_event(event)` 把 relay record 事件幂等写入 `mail.message` / `agenthub.turn` / `agenthub.delivery`。
- 默认忽略 `message.updated`，只在 `message.created` / `message.final` 落最终消息。
- 幂等键：`agenthub_relay_message_id` + `agenthub_stream_id`；`meta.origin_record_id`（`mail.message,<id>`）用于跳过 Odoo 已落库的 Discuss 用户消息。
- Discuss 投影：通过 `discuss.channel.message_post` 以 agent service user 身份发帖；外部渠道写入 `agenthub.thread` 的 `mail.message`。
- `agenthub.record.cursor._cron_pull()` 从 relay `/v1/record` 拉取，携带 `X-AgentHub-Recorder-Token`；批次成功后更新 cursor 并 ack。
- Odoo 配置：`agenthub.relay_url`、`agenthub.relay_secret`、`agenthub.relay_recorder_token`、`agenthub.relay_config_token`、`agenthub.recorder_batch_limit`。
- 配置快照：Odoo 提供 `GET /agenthub/relay/config`，要求 `X-AgentHub-Config-Token`；relay 按版本拉取并原子替换 agent token/identity/binding 缓存。
- 当前 cron 间隔 1 分钟；<5s SLO 需要后续长轮询/推送 worker。

### mail.message 扩展

`_inherit = "mail.message"`，与 `llm` 的语义对齐，但 core 不依赖 `llm`：

- subtype：`agenthub.mt_user` / `mt_assistant` / `mt_tool` / `mt_system`
- `agenthub_role`：由 subtype 计算并存储（`user` / `assistant` / `tool` / `system`）
- `agenthub_body_json`：tool_calls、tool_result、结构化内容
- `agenthub_is_error`：展示但不进入上下文（用前缀避免与 `llm.is_error` 冲突）
- `agenthub_content`：渠道侧原始文本/markdown；`body` 存渲染后的 HTML
- `agenthub_relay_message_id`：relay 侧消息 id，用于 recorder 幂等
- `agenthub_relay_turn_id` / `agenthub_turn_id`：问答关联
- `agenthub_stream_id`：流式回复关联
- `agenthub_external_id` / `agenthub_reply_to_external_id`：渠道侧消息 id 与回复关联
- `agenthub_direction` / `agenthub_delivery_state`：legacy/审计字段；不再作为出站队列

约定：

- 最小记录单元是语义 message（user/assistant/tool/system），不是流式 chunk。
- 一个 `stream_id` 只建一条占位消息，最终帧收尾；Odoo recorder 默认只落最终消息。
- tool call 放 assistant 的 `body_json.tool_calls`；tool result 是独立的 `tool` message + `body_json`。
- 中间帧/工具事件保留在 relay 热日志；确需完整回放时再引入短保留 event 表。

## 扩展点

core 定义两个抽象 component：

- `agenthub.channel.adapter`：`send(channel, message)`，用于 `in_process`/本地渠道。
- `agenthub.agent.adapter`：`reply(agent, message)`，用于 `in_process` agent（如 `llm.agent`、人工）。

解析按 usage 后缀（`usage == channel_type` / `agent_type`），与 InfoHub 一致，避免 `SeveralComponentError`。

外部 agent（`runtime=relay`）**不走 `reply()`**：Odoo 创建 turn 并写入 publish outbox，由 relay 投递给 agent-box；回包经 record feed 回到 Odoo。agent addon 仍负责 `selection_add`、配置字段、token/service user 管理。

新增 channel/agent 只加独立 addon：

- channel addon：`_inherit` 加字段 + `selection_add` + 对应 gateway/component。
- agent addon：`_inherit` 加字段 + `selection_add` + `agent_type`/runtime 实现。

## 路由与数据流

### 外部渠道

1. relay channel gateway 收到消息，归一化为 `message.created` envelope。
2. relay router 用 `peer_ref` 查配置缓存：identity → user → binding → agent。
3. 生成确定性 `thread_key`，创建 turn，写入 agent inbox；同时写 record 流。
4. agent-box 领取、流式回包；final 后写入 channel outbox。
5. gateway 发送给用户；Odoo recorder 异步拉取 record 流，落 `mail.message` / `agenthub.turn` / `agenthub.delivery`。

### Discuss

1. 用户在 `discuss.channel` 里与 agent 的 service user partner 会话。
2. `agenthub_discuss` 在 `_message_post_after_hook` 里检测绑定到 agenthub 的频道，跳过 agent/OdooBot 回帖，与消息同事务写 `agenthub.publish` outbox。
3. worker 调 relay publish 接口；事件带 `thread_key=discuss.channel:<id>`、`agent_id`，以及 `meta.origin_record_id=mail.message,<id>`。
4. agent 回包 final 后写 record；Odoo recorder 以 service user 身份投影回 `discuss.channel`。用户原始消息已由 Odoo 落库，recorder 按 `origin_record_id` 跳过，不重复创建。

Odoo 不参与实时路由；它只做入站发布、最终消息投影和归档。

### cron/命令

1. `ir.cron` 创建 `agenthub.command`，写 publish outbox。
2. relay 创建 turn，投递给目标 agent。
3. 回包按 `reply_mode`：`none` 只落库；`owner` 通知 owner；`thread` 回到指定会话。

### 流式

- agent 首帧 `message.updated`（`final=false`）；中间帧按 `seq` 更新同一 `stream_id`。
- relay 节流后转发；Odoo recorder 默认忽略中间帧，只落 `message.final`。
- 若后续 Discuss 需要流式展示，再让 recorder 对占位消息做节流更新。
- agent 崩溃/租约过期：未 ack 的 delivery 重投；agent 用 `(turn_id, stream_id, seq)` 幂等重放。

## Relay（独立服务）

Relay 的完整职责、状态机、接口见：

- `relay-v1.md`：组件、队列、turn/delivery/outbox/presence 状态机、agent WS、publish、record feed、config sync、admin、背压、安全、HA。
- `relay-message-envelope.md`：统一 envelope、event_type、payload schema、幂等、校验、Odoo 映射。

设计要点：

- **连接**：agent WebSocket 为主，HTTP 长轮询降级；企微 gateway 持有 aibot WS，每个 `bot_id` 用租约保证单 owner。
- **路由**：只按显式 identity/binding/thread，不做语义路由。
- **投递**：至少一次 + 租约 + ack + 重试 + DLQ；同一 thread 串行，不同 thread/agent 并发。
- **状态**：turn/delivery/presence/thread 活跃态放 Redis KV；durable 事件放 Redis Streams（NATS JetStream 可替换）。
- **归档**：所有语义事件写 `record` 流；Odoo recorder 主动拉取并维护 cursor。
- **背压**：每 agent/每 channel 队列上限、未 ack 上限、record lag 上限；触发时拒绝新入站，不丢已接受消息。
- **安全**：agent token 哈希、按 agent 隔离 inbox；Odoo publish 用 HMAC；渠道密钥不落日志。

## 企微 channel 与 OpenClaw agent（legacy）

当前仓库里的两个实现是 **legacy**，保留给已有安装：

- `agenthub_wecom`：在 Odoo gevent worker 内实现 aibot WebSocket 服务端。目标架构把它移到 relay channel gateway；同一 `bot_id` 不能同时由 Odoo 和 relay 持有，否则互踢。
- `agenthub_openclaw`：Odoo 进程内的 OpenClaw 回复语义适配器。目标架构由外部 agent-box 通过 relay 接入；该 addon 不再作为主路径。

legacy 实现的协议细节仍以各自 addon 的 `docs/` 为准。新部署不应同时启用 legacy Odoo WS 与 relay gateway。

## 关键取舍与理由

### 为什么 relay 独立、Odoo 不在热路径

>100 agent、50 万消息/天时，Odoo 作为实时路由/队列会成为瓶颈：gevent/HTTP worker、ORM 写入、DB 轮询和 Discuss 通知互相竞争。Relay 独立后可以水平扩展、使用专用队列、按 agent 隔离背压；Odoo 只做它擅长的配置、UI、权限和归档。

### 为什么 Odoo 仍然记录所有语义消息

审计、Discuss UI、权限和查询都需要 Odoo 的长期数据。Relay 的 durable log 是操作事实来源，Odoo 的 `mail.message` 是可查询归档。默认异步 recorder，换取吞吐；若要求“投递前可查”，可把用户消息改为同步写前记录，但会重新引入 Odoo 热路径。

### 为什么消息仍落 mail.message，而不是另建 agenthub.message

`mail.message` 直接复用 Discuss UI、附件、流式占位更新和 `llm` 的 role/body_json 语义。只要 recorder 批量直写、避开 `message_post` 的重开销、默认只落最终消息，就能支撑目标规模。若后续 profiling 证明 `mail.message` 是瓶颈，再引入轻量归档表 + 投影，而不是现在就拆两张表。

### 为什么每个 agent 一个 service user

Discuss 里用户“直接选到 agent”的前提是每个 agent 有唯一的 Odoo user/partner。共用 Odoobot 或多个 agent 共用一个用户，就无法区分会话、无法审计、也无法独立收窄权限。service user 是身份与权限边界，agent-box 进程通过 token 以该身份读写。

### 为什么 thread_key 由 relay 确定性生成（外部渠道）

relay 不查 Odoo thread 表：`(channel, peer, agent)` 已确定唯一 thread。Odoo recorder 收到事件后 ensure thread 即可。这样 relay 的路由是无状态/缓存式的，减少跨服务查询。

### 为什么 channel 与 agent 仍然正交

传输（消息怎么到）与应答（这段对话怎么理解/回复）是两个维度，且渠道消息无法识别对端是哪个 agent。把 agent 塞进 channel 会把传输和运行时焊死；拆开后每轴独立扩展。

### 为什么 Odoo publish 用 outbox、record 用拉取

- Odoo → relay：publish outbox 与业务事务同提交，保证 Discuss/cron 消息不丢；worker 重试，relay 按 event_id 去重。
- relay → Odoo：Odoo recorder 主动拉取并维护 cursor，Odoo 宕机不阻塞 relay；relay 用 lag 指标做背压。

## 被否决的方案

| 方案 | 否决理由 |
|---|---|
| 一对一硬编码「Odoo↔企微↔OpenClaw」 | 新增传输或 agent 都要重写路由/落库/重试，无法沉淀为框架。 |
| agent 依赖 channel | 在代码里断言“某个 agent 只能走某个 channel”；渠道消息本无法识别 agent。 |
| plain `agenthub.thread` + 独立 `agenthub.message` 表 | 会话就是聊天，`mail.thread` 白送 UI/流式/附件；内容与投递拆两张表徒增同步。当前保留 `mail.message`，投递只做审计副本。 |
| **Odoo 作为实时 router/queue** | >100 agent 时受 worker/ORM/DB 轮询限制；路由、队列、长连接移到 relay。 |
| **每个 agent 轮询 Odoo 的 mail.message** | N 个 agent × 轮询频率会打爆 Odoo；改为 relay WS + 按 agent 的 inbox 流。 |
| **所有事件同步写前记录到 Odoo** | 吞吐受 Odoo 写入限制；默认异步 recorder，必要时只对用户消息做同步写前。 |
| **每条流式帧都落 mail.message** | 行数和写入量成倍增加；一个 stream_id 一条占位/最终消息即可。 |
| **所有 agent 共用 Odoobot / 一个 Odoo 用户** | Discuss 无法区分 agent，审计和权限无法独立。 |
| **目标架构中让 Odoo 继续持有企微 WS** | Odoo 会留在热路径；且与 relay gateway 争抢同一 bot_id 会互踢。仅保留为 legacy。 |
| 复用 `bus` 的 `WebsocketConnectionHandler` 直接跑 aibot | 该 handler 深度耦合 bus 通知协议，不是通用 JSON 协议承载。 |
| 独立的裸 `websockets` 进程（无路由/无持久化） | 早期否决的是“只有 socket、没有 relay 职责”的进程；v1 relay 有明确的队列、路由、状态机和归档接口。 |
| agent 与 channel 合并成一个模型 | 无法表达两轴正交，会把类型搅成一维笛卡尔积。 |
| 用 `_component_match` 消歧 | 框架在 collection/model 之外无法消歧，会抛 `SeveralComponentError`；usage 后缀天然唯一。 |
| impersonate owner | 审计里全是 owner，分不清“人干/agent 干”；且 Odoo 无“比某用户更窄”的原生机制。 |

## 执行身份与权限

### 三个身份

| 身份 | 字段 | 作用 | 用于执行？ |
|---|---|---|---|
| 归属/授权人 | `owner_user_id` | agent 属于谁、谁授权；审计归属、权限上限 | 否 |
| 执行身份 | `user_id`（service user） | agent 的工具调用/读写实际跑在谁的环境 | 是 |
| 显示身份 | `partner_id` | Discuss 里的消息作者（= `user_id.partner_id`） | 否 |

### 执行契约

- `in_process` agent：`_agent_env()` 返回 `env(user=self.user_id, su=False)`；caller 用 `with_user` 绑定执行身份，工具/记录访问用 `self.env[model]`，**never sudo**。
- `relay` agent：Odoo 用 service user 记录消息作者与审计；agent-box 通过 relay token 认证，实际 Odoo 权限由 token 对应的 service user 决定。Relay 不得绕过 Odoo 权限。
- 约束：`user_id` 必须是内部、active 用户；活跃 agent 的 service user 唯一；允许 `user_id == owner_user_id`，但推荐专职 service user。
- 消息作者：`message_post(author_id=agent.partner_id)`；UI 上 agent 与人类可辨。
- Record rule：按 `agent_id` / `owner_user_id` 收敛；`agenthub.group_agenthub_user` 只看/管自己的 agent 与 thread，`agenthub.group_agenthub_admin` 看全部。

## 管理 UI、Token 与命令

- 菜单 `Agent Hub → Agents`：list/form 管理 agent（name、runtime、owner、service user、token、workspace）。
- Token：生成时展示一次，存储 `token_hash`；支持轮换。relay 通过配置快照拿到 hash。
- 新增 `Identities`、`Bindings`、`Commands` 管理入口（或嵌入 agent/channel 表单）。
- `agenthub.command` 可由 `ir.cron` 创建；表单支持 `reply_mode`。
- 权限：`agenthub.agent` 对 `agenthub.group_agenthub_user` 开放 CRUD；record rule 按 `owner_user_id` 隔离，`agenthub.group_agenthub_admin` 看全部。两个组都不默认授予内部用户。

## 验收与测试边界

- Odoo addon tests（`--test-tags /agenthub`）覆盖：模型/约束、component 扩展点、publish outbox、recorder 幂等、config 快照、Discuss 投影、token/权限。
- Relay 由独立服务自己的 contract/integration tests 覆盖：envelope、路由、状态机、WS、租约、背压、DLQ、bot lease、HA 重连。
- 集成测试使用 fake relay + fake channel，保证无外部网络/API key 也能跑。
- 验收项见 `acceptance.md`。

## 后续扩展

- Relay 多实例 router 分片、跨机房。
- Discuss 流式中间态投影。
- 新 channel：Telegram/Web/邮件；新 agent：OpenCode/内部 `llm.agent`/人工。
- Relay 技术选型：Redis Streams vs NATS JetStream。
- 归档保留策略、冷存储、跨 agent 审计报表。
- 群聊/多用户会话语义。

## 参考

- `relay-v1.md` — relay 职责、状态机、接口。
- `relay-message-envelope.md` — 统一 envelope。
- `../../agenthub_relay/` — relay v1 骨架（内存 store；Redis/HA/企微 gateway 待补）。
- `agenthub_wecom/docs/`、`agenthub_openclaw/docs/` — legacy 实现细节。
