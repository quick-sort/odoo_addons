# AgentHub Relay — 统一消息 Envelope（v1 草案）

> 状态：草案，2026-11-01。评审后合并进 `design.md` / `acceptance.md`。
> 适用范围：relay、Odoo publisher/recorder、agent-box、channel gateway。
> 关联文档：`design.md`、`relay-v1.md`。

## 1. 目标与原则

- **一个 envelope 走到底**：渠道入站、Odoo 发布、relay 路由、agent 回包、Odoo 归档，全部使用同一结构。
- **记录语义消息，不记录每个 token 帧**：一次流式回复只对应一条 `stream_id`；中间帧用 `message.updated` 表达，终帧收尾。
- **角色对齐 `llm`**：`user` / `assistant` / `tool` / `system`；tool call 放 assistant 的 `body_json.tool_calls`，tool result 是独立的 `tool` 消息。
- **至少一次投递 + 幂等**：relay 不承诺 exactly-once；消费方用稳定键去重。
- **内容与渲染分离**：`content` 是原始文本/markdown；HTML 渲染、Discuss 投影是 Odoo recorder 的职责。
- **Relay 不做长期存储**：envelope 是传输与归档事件，不是归档本身。

## 2. 顶层结构

```json
{
  "event_version": 1,
  "event_id": "evt_01JABCDEF...",
  "event_type": "message.created",
  "occurred_at": "2026-11-01T12:34:56.789Z",
  "source": {
    "type": "channel",
    "id": "wecom:prod"
  },
  "route": {
    "agent_id": 12,
    "channel_id": 34,
    "thread_key": "thread:123",
    "peer_ref": "zhangsan",
    "user_id": 56,
    "reply_mode": null
  },
  "turn": {
    "turn_id": "turn_01JABCDEF...",
    "seq": 0,
    "state": "queued",
    "attempt": 1,
    "deadline": "2026-11-01T12:36:56.789Z"
  },
  "payload": {},
  "meta": {
    "trace_id": "trace_...",
    "config_version": 42,
    "origin": "channel",
    "origin_record_id": null
  }
}
```

| 字段 | 类型 | 必填 | 说明 |
|---|---|---|---|
| `event_version` | int | 是 | Envelope 主版本；v1 为 `1` |
| `event_id` | string | 是 | 全局唯一事件 id（ULID/UUID）；relay 用它去重 |
| `event_type` | string | 是 | 见第 3 节 |
| `occurred_at` | string | 是 | ISO-8601 UTC |
| `source.type` | string | 是 | `channel` / `odoo` / `agent` / `relay` / `system` |
| `source.id` | string | 是 | 渠道实例 id、agent id、Odoo 实例标识等 |
| `route` | object | 视类型 | 消息/命令/投递控制必填；presence 可省 |
| `turn` | object | 视类型 | 与一次问答相关的事件必填 |
| `payload` | object | 是 | 由 `event_type` 决定结构 |
| `meta` | object | 否 | trace、配置版本、重试次数等 |

### 2.1 route

| 字段 | 类型 | 说明 |
|---|---|---|
| `agent_id` | int/string | Odoo 的 `agenthub.agent.id` |
| `channel_id` | int/string | Odoo 的 `agenthub.channel.id`；Discuss 可为空 |
| `thread_key` | string | 不透明、稳定的会话键；Odoo 生成并持有语义 |
| `peer_ref` | string | 渠道侧对端标识（企微 `userid`、Discuss partner/频道等） |
| `user_id` | int/string | 映射后的 Odoo 用户 id |
| `reply_mode` | string | 仅命令：`none` / `owner` / `thread` |

`thread_key` 建议由 Odoo 统一生成：

- 企微/外部渠道：`agenthub.thread:<id>`
- Discuss：`discuss.channel:<id>`
- 命令：`command:<id>`

具体格式由 Odoo 决定，relay 只当作不透明键使用。

### 2.2 turn

| 字段 | 类型 | 说明 |
|---|---|---|
| `turn_id` | string | 一次 user/command → agent → 回复的稳定 id |
| `seq` | int | 同一 turn 内单调递增；用于顺序 |
| `state` | string | `queued` / `running` / `completed` / `failed` / `cancelled` / `expired` |
| `attempt` | int | 投递/执行尝试次数，从 1 开始 |
| `deadline` | string | 可选；超过则过期 |

### 2.3 meta

| 字段 | 类型 | 说明 |
|---|---|---|
| `trace_id` | string | 跨 gateway/router/agent/recorder 的追踪 id |
| `config_version` | int | 事件产生时的配置版本 |
| `origin` | string | `channel` / `odoo` / `agent` / `system`；用于 recorder 去重 |
| `origin_record_id` | string/null | 消息已在 Odoo 存在时的记录引用，如 `mail.message,123`；recorder 不再重复创建 |
| `retry_count` | int | 可选；重试次数 |

**Discuss 入站的去重规则**：用户在 `discuss.channel` 发的消息已经由 Odoo 落库。Odoo publisher 必须在 `meta.origin="odoo"`、`meta.origin_record_id="mail.message,<id>"` 中标明，recorder 收到后只确保 thread/turn/delivery，不再创建或投影同一条用户消息。

## 3. event_type 与 payload

| event_type | payload | 说明 |
|---|---|---|
| `message.created` | `message` | 新建语义消息；非流式消息或流式首帧 |
| `message.updated` | `message` | 流式中间帧；`final=false` |
| `message.final` | `message` | 流式终帧；`final=true` |
| `command.created` | `command` | cron/系统下发命令 |
| `turn.started` | `control` | agent 开始处理 turn |
| `turn.completed` | `control` | turn 正常结束 |
| `turn.failed` | `control` | turn 失败 |
| `turn.cancelled` | `control` | turn 被取消 |
| `delivery.claimed` | `control` | agent 领取投递 |
| `delivery.acked` | `control` | agent 确认完成 |
| `delivery.failed` | `control` | 投递失败 |
| `delivery.expired` | `control` | 租约过期，重新入队 |
| `presence.changed` | `presence` | agent 在线状态；仅 relay 使用，不归档 |
| `attachment.created` | `attachment` | 附件上传完成或元数据登记 |

## 4. payload 结构

### 4.1 message

```json
{
  "message_id": "msg_01JABCDEF...",
  "role": "assistant",
  "content": "partial markdown",
  "body_json": null,
  "stream_id": "stream_01JABCDEF...",
  "seq": 3,
  "final": false,
  "is_error": false,
  "author": {"type": "agent", "id": 12},
  "external_id": "msgid-123",
  "reply_to_external_id": "req-456",
  "attachments": [],
  "created_at": "2026-11-01T12:34:56.789Z"
}
```

| 字段 | 类型 | 说明 |
|---|---|---|
| `message_id` | string | relay 侧稳定 id；Odoo recorder 建立到 `mail.message.id` 的映射 |
| `role` | string | `user` / `assistant` / `tool` / `system` |
| `content` | string | 原始文本/markdown；不是渲染后的 HTML |
| `body_json` | object/null | 结构化内容：tool_calls、tool result、卡片等 |
| `stream_id` | string/null | 流式回复的稳定 id；非流式为 null |
| `seq` | int | 同一 `stream_id` 内单调递增 |
| `final` | bool | 流式终帧为 true；非流式消息为 true |
| `is_error` | bool | 展示但不进入上下文 |
| `author` | object | `type`: `user` / `agent` / `system`；`id` 为对应 id |
| `external_id` | string/null | 渠道侧消息 id，用于去重/回复 |
| `reply_to_external_id` | string/null | 渠道侧“回复谁”的关联 id |
| `attachments` | array | 见 4.5 |

tool call / result 约定（与 `llm` 一致）：

```json
// assistant 消息中的 tool_calls
{
  "role": "assistant",
  "content": "",
  "body_json": {
    "tool_calls": [
      {
        "id": "call_1",
        "name": "read_file",
        "arguments": {"path": "main.py"}
      }
    ]
  }
}
```

```json
// tool result 消息
{
  "role": "tool",
  "content": "",
  "body_json": {
    "tool_call_id": "call_1",
    "name": "read_file",
    "result": "print('hi')",
    "is_error": false
  }
}
```

### 4.2 command

```json
{
  "command_id": "cmd_01JABCDEF...",
  "name": "run_tests",
  "payload": {"project": "default"},
  "reply_mode": "thread",
  "thread_key": "thread:123",
  "created_by": 7
}
```

- `reply_mode`：`none`（只落库）、`owner`（通知 agent owner）、`thread`（回到指定会话）。
- 命令在 agent 侧按一次 turn 处理；回包仍用 `message.*` 事件。

### 4.3 control

```json
{
  "delivery_id": "dlv_01JABCDEF...",
  "leg": "to_agent",
  "state": "acked",
  "attempt": 1,
  "error": null
}
```

用于 `turn.*` / `delivery.*`。`leg` 为 `to_agent` 或 `to_user`。

### 4.4 presence

```json
{
  "agent_id": 12,
  "state": "online",
  "last_seen": "2026-11-01T12:34:56.789Z",
  "capacity": 4,
  "queue_depth": 0
}
```

`state`：`connecting` / `online` / `busy` / `draining` / `offline`。

### 4.5 attachment

```json
{
  "attachment_id": "att_01JABCDEF...",
  "name": "report.pdf",
  "mime": "application/pdf",
  "size": 123456,
  "sha256": "…",
  "url": "https://relay.example/files/…?signature=…",
  "kind": "document"
}
```

- 大文件走对象存储；envelope 只带引用。
- Odoo recorder 负责转为 `ir.attachment` 或 storage backend 引用。

## 5. 幂等与顺序

### 5.1 Relay 去重

- `event_id` 全局唯一；relay 保留去重窗口（建议 7 天）。
- 重复事件返回成功但不重复入队。

### 5.2 Odoo recorder 去重

- 消息：`(thread_key, turn_id, stream_id, seq)` 唯一；无 `stream_id` 时用 `(thread_key, turn_id, message_id)`。
- 命令：`command_id` 唯一。
- 控制事件：`event_id` 唯一。
- recorder 维护 `relay message_id → mail.message.id` 映射。

### 5.3 顺序

- `turn.seq` 在同一 turn 内单调递增。
- `message.seq` 在同一 `stream_id` 内单调递增。
- relay 保证同一 `thread_key` 的事件顺序；Odoo recorder 批量写入时也必须保持同 thread 顺序。

## 6. 校验规则

- `event_version` 必须受支持；未知主版本拒绝。
- `event_type` 必须在白名单内。
- `message.created`：`final` 必须为 true；`role` 必须在枚举内。
- `message.updated`：必须带 `stream_id`，`final=false`。
- `message.final`：必须带 `stream_id`，`final=true`。
- `role=tool` 必须带 `body_json.tool_call_id`。
- `body_json.tool_calls` 必须是数组，每项含 `id` / `name` / `arguments`。
- `command.created`：必须带 `command.command_id`、`name`、`reply_mode`。
- 内容上限建议：`content` 256 KB、`body_json` 1 MB、单附件 20 MB；超限拒绝并返回 400。
- 未知字段忽略，保持向前兼容。

## 7. 与 Odoo 模型的映射

| Envelope | Odoo |
|---|---|
| `message.created/updated/final` | `mail.message`；role 映射 subtype |
| `message.content` | `agenthub_content`（原始 markdown） |
| `message.body_json` | `agenthub_body_json` |
| `message.is_error` | `agenthub_is_error`（避免与 `llm.is_error` 冲突） |
| `message.stream_id` / `seq` | `agenthub_stream_id` + 流式占位更新 |
| `message.external_id` | `agenthub_external_id` |
| `message.reply_to_external_id` | `agenthub_reply_to_external_id` |
| `message.author` | `author_id = agent.service_user_id.partner_id` 或用户 partner |
| `turn.*` | `agenthub.turn` |
| `command.created` | `agenthub.command` |
| `delivery.*` | `agenthub.delivery`（审计副本） |
| `presence.changed` | 不归档；更新 relay；可回写 `agenthub.agent.last_seen` |
| `attachment.created` | `ir.attachment` 或 storage backend 引用 |
| `meta.origin_record_id` | 已存在的 `mail.message` 引用；recorder 只做关联，不重复创建 |

流式写入策略：

- relay 可以转发 `message.updated`，但 Odoo recorder 默认**只落最终消息**，避免每条中间帧都写 `mail.message`。
- 若后续 Discuss UI 需要流式展示，再让 recorder 对占位消息做节流更新。
- 中间帧仍保留在 relay 的热日志中，供回放/排查。

## 8. 版本与兼容

- 新增可选字段不升版本；删除/改语义必须升主版本。
- relay 可同时接受 `event_version` 1 和未来的兼容小版本。
- Odoo recorder 忽略未知 `event_type` 并记录警告，不阻塞后续事件。

## 9. 待定项

- `message_id` 由 relay 还是 Odoo 生成（当前建议 relay 生成，Odoo 维护映射）。
- 附件是引用对象存储还是回传到 Odoo（当前建议引用 + recorder 转存）。
- 命令 payload 的 schema 是否需要按 `command.name` 注册。
- Discuss 的 `thread_key` 是否直接使用 `discuss.channel.id`。
