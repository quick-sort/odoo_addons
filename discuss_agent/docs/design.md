# discuss_agent — 系统设计

## 总览：多态 responder + 统一生命周期

`discuss_agent` 定义**一个接口记录 `discuss.agent`**，把「具体的 responder」
（`llm.agent` / `agenthub.agent` / 未来的任何 agent）绑定到 Discuss 共同关心的
三件事上：回复人格、触发策略、回复执行契约。

「谁回复」由 `res_model` + `res_id` **多态引用**到具体记录；「怎么回复」由
`_discuss_execute` **协议方法**分派给具体实现。core 既不 import 具体 responder，
也不知道「推模式 / 拉模式」的差异——它只认一个协议。

```
             ┌──────────────────────────────────────────────┐
             │               discuss.agent (接口)            │
             │  res_model / res_id  → 具体 responder          │
             │  discuss_user_id     → 回复人格                │
             │  discuss_trigger_mode→ 触发策略                │
             │  _discuss_execute()  → 协议分派                │
             └──────────────┬───────────────┬────────────────┘
                            │               │
              ┌─────────────▼─────┐  ┌──────▼──────────────────┐
              │ llm.agent（推）    │  │ agenthub.agent（拉）      │
              │ Odoo 主动 invoke   │  │ agent-box JSON-RPC 轮询  │
              │ 同步返回 result     │  │ 返回 {pending} + 外部回帖 │
              └───────────────────┘  └─────────────────────────┘
```

## 数据模型

### discuss.agent（接口 / 多态宿主）

| 字段 | 类型 | 作用 |
|---|---|---|
| `name` | Char | 显示名 |
| `active` | Boolean | 启用 |
| `agent_type` | Selection（core 置空） | responder 种类，桥接 addon `selection_add` |
| `res_model` | Char | 具体 responder 的模型技术名 |
| `res_id` | Integer | 具体 responder 的记录 id |
| `discuss_user_id` | M2o res.users | 回复人格（回复气泡的作者） |
| `discuss_enabled` | Boolean | 是否在 Discuss 启用 |
| `discuss_trigger_mode` | Selection | both / direct_chat / mention |

### discuss.reply.job（pending 载体）

一条「某消息欠某 agent 一条回复」的记录。入队时固化**人格**与**执行身份**：

- `agent_id` → `discuss.agent`
- `channel_id` / `message_id` → 触发源
- `reply_partner_id` → 回复人格（作者）
- `source_user_id` / `source_company_id` → 执行身份（权限）
- `page_context` → 入队时校验过的页面元数据快照
- `attachment_ids` → 入方向附件快照（入队时捕获，执行期不可变）
- `state` → pending / processing / done / error
- `claim_token` / `attempt_count` / `started_at` / `error_message` → 认领与簿记

唯一约束 `UNIQUE(agent_id, message_id)` 保证同一消息对同一 agent 只入队一次。

### discuss.channel 钩子

`_message_post_after_hook` 里调用 `discuss.agent._discuss_dispatch`，用 try/except
包裹，**绝不回滚用户已经发出的消息**。

## 接口契约

### 1. 触发（discuss.channel）

```
_discuss_user_can_use_agent(agent, user) -> bool   # 用户是否有权用该 agent
_discuss_should_trigger(agent, message, msg_vals) -> bool  # 是否触发
```

`_discuss_should_trigger` 规则（对齐 llm_discuss）：

- 跳过 bot 自己的消息、非 `comment` 消息；
- `direct_chat`：1:1 私聊且 bot 是成员；
- `mention`：`partner_ids` 里 @ 了 bot；
- `both`：二者任一。

### 2. 入队（discuss.agent）

```
_discuss_dispatch(channel, message, msg_vals)      # 遍历 enabled agent，判定 + 入队
_discuss_enqueue_reply(channel, message, source_user, reply_partner, page_context) -> bool
```

入队是幂等的（`UNIQUE(agent_id, message_id)` + 先查再建），固化
`source_user`（执行身份）、`reply_partner`（回复人格）与 `page_context`（页面快照）
后立即返回，不阻塞发消息。`page_context` 由前端放进
`context.discuss_agent_page_context`，`_discuss_dispatch` 用
`_discuss_normalize_page_context` 校验后入队。

### 3. 执行（discuss.agent → 具体 responder）

```
_discuss_execute(*, execution_user, company, query, background=None, thread_vals=None, attachment_ids=None, stream=False) -> dict
```

这是**唯一因 responder 而异的契约**，返回值两种形态：

| 形态 | 返回值 | 谁交回 result |
|---|---|---|
| 同步（推模式，llm.agent） | `{"result_html"/"result"/"thread_id"}` 或 `{"error"}` | 调用现场 |
| 异步（拉模式，agent-box） | `{"pending": True}` | 外部运行时完成后回调 `_complete` |

`background` 承载页面背景（`{"page": ...}` / `{"record": ...}`），`thread_vals`
承载隐藏线程关联（`{"model", "res_id"}`），均由 `_build_background` 从
`page_context` 推导；`attachment_ids` 是入方向附件（入队快照）。`discuss.agent.
_discuss_execute` 只做分派：`_discuss_resolve()` 拿到具体记录，调它的同名协议
方法。协议方法由桥接 addon 用 `_inherit` 加在具体模型上。

### 4. 生命周期与完成（discuss.reply.job）

```
_claim_pending(agent_types=None) -> job          # FOR UPDATE SKIP LOCKED 原子认领，可按 responder 类型过滤
_lock_owned_claim(claim_token) -> bool           # fencing：校验认领 token 仍归本 worker
_expire_stale_jobs()                             # 超时 fence，不自动重放（工具副作用）
_gc_processed_jobs()                             # 清理 done/error 旧记录
_execution_user_and_company() -> (user, company) # fail-closed 解析执行身份
_build_background(execution_user, company) -> (background, thread_vals)
_set_bot_typing(True/False) / _clear_bot_typing_if_idle()
_post_reply(body)                                # 窄 sudo，仅发帖，作者 = reply_partner
_process_one()                                   # 推模式：完整处理一条 job（typing → 生成 → fencing → 回帖 → done）
_process_pending(agent_types, batch_size)        # 推模式循环：stale + claim + process + gc
_complete(result) -> bool                        # 回帖 + 置 done
_complete_error(error)                           # 置 error
```

同步消费方（worker，如 llm_discuss）：cron 调 `_process_pending(agent_types=["llm"])`。
异步消费方（agent-box）：轮询 `_claim_pending` → 外部生成 → 回调 `_complete`。
两种消费方共享同一套 fencing / 超时 / GC 状态机。

## 多态如何实现

**多态 = `res_model` + `res_id` 运行时引用 + 协议方法鸭子分派**，不用 Odoo 的
`Reference` 字段，也不用 component collection：

```python
def _discuss_resolve(self):
    return self.env[self.res_model].browse(self.res_id).exists()

def _discuss_execute(self, **kw):
    target = self._discuss_resolve()
    execute = getattr(target, "_discuss_execute", None)   # 协议方法
    if execute is None:
        raise UserError(...)
    return execute(**kw)
```

选择这个方案的理由：

1. 两个 responder 是**不同的模型**（`llm.agent` vs `agenthub.agent`），无法继承
   同一个 base；component collection 按「同模型不同 type」消歧，不适合跨模型。
2. `res_model` + `res_id` 是 Odoo 表达「指向任意模型的一条记录」的标准轻量方式，
   core 不 import 任何具体模型，依赖方向保持单向。
3. 协议方法让「推模式」和「拉模式」都收敛到同一个 `_discuss_execute` 签名，
   区别只在返回值（`result` vs `pending`）。

桥接 addon 接入一个新 responder 要做两件事：

1. `_inherit = "discuss.agent"` 加 `agent_type = fields.Selection(selection_add=[(...)])`；
2. `_inherit = "具体模型"` 加 `_discuss_execute` 协议方法（实现同步或异步形态）。

## 权限模型

对齐 llm_discuss 的「回复人格 ≠ 执行身份」红线：

- **执行身份**：`source_user`（谁发消息）。消费方用
  `_execution_user_and_company()` 解析，`fail-closed`（身份丢失即报错），工具与
  记录读写都在这个 user 的 env 下跑，**绝不 sudo**。
- **回复人格**：`reply_partner_id`（`discuss_user_id.partner_id`）。回帖用
  `channel.sudo().message_post(author_id=reply_partner_id)`——sudo 只作用于「发帖」
  这一件事，不传给工具。
- 对 agent-box：其 API key 绑定的账号只用于 JSON-RPC 认证与回帖，**不等于**
  `source_user`；`source_user_id` 从 job 里读出，工具执行时切到 source_user。

## 与 llm_discuss 的关系

`llm_discuss` 已收敛为 `discuss_agent` 的 llm 桥接 addon（依赖 `discuss_agent`）。
普通 Discuss 触发走 `discuss_agent` 统一接口；OdooBot 接管暂留 llm_discuss 本地
`llm.discuss.reply.queue`。

- `discuss_agent` 是**接口抽象 + pending 载体的完整生命周期**（fencing / typing /
  page_context / GC 已迁入 core）。
- `llm_discuss` 是**llm 桥接**：`agent_type="llm"` + `_discuss_execute` 协议方法 +
  `discuss.agent` 同步 + worker cron（`_process_pending(agent_types=["llm"])`）。
- 待迁入：附件透传（需先改 llm 核心 invoke 链）、OdooBot 接管。

## 被否决的方案

| 方案 | 否决理由 |
|---|---|
| 直接改造 `llm_discuss` 的 `agent_id` 为多态 | 动已验证的代码，且把「llm 专属」与「接口」耦合，违背并行接口层定位 |
| component collection 表达跨模型多态 | collection 只按「同模型不同 type」消歧，跨模型需额外宿主，复杂度换不来收益 |
| `Reference` 字段（`res_model_id` + `res_id`） | 无 ondelete/索引能力，且 Odoo 的 Reference 语义在本场景没有额外价值 |
| 让 `agenthub.agent` 直接复用 `llm_discuss` | 两者执行模型相反（推 vs 拉），强行复用会把拉模式塞进推模式的 worker |
| 在 core 里注册 cron 调度 | 消费方是「实现」不是「接口」，agent-box 是外部轮询；core 只提供无 scheduler 的 `_process_pending` 处理循环，具体 cron 由桥接 addon 注册 |
