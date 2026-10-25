# discuss_agent — 需求与边界

## 目标

把「谁在 Discuss 里回复一条消息」抽象成一个**接口**，让不同种类的 AI agent
作为可插拔的 responder 接入，共用同一套触发、权限、回复生命周期。

两类已锚定的 responder：

| responder | 谁主动 | 生成回复的位置 |
|---|---|---|
| `llm.agent`（内置） | Odoo 主动调 provider | Odoo 进程内 |
| `agenthub.agent` / agent-box（外部） | 外部 agent 主动 JSON-RPC 轮询 | Odoo 进程外 |

## 硬约束（红线）

1. **异步**：触发一条消息的回复**绝不阻塞**用户发消息。触发只登记 pending
   job，回复由消费方异步完成。
2. **权限跟用户一致**：执行身份是发消息的 `source_user`，不是系统/root，也
   不是固定的 service user。回帖只对「发帖」这一件事用窄 sudo。
3. **回复人格 ≠ 执行身份**：`reply_partner_id`（谁的名义回）与
   `source_user_id`（用谁的权限执行）是两个独立字段，入队时固化、不可变。
4. **core 不依赖任何具体 responder**：本 addon 不 import `llm`、不 import
   `agenthub`，只依赖 `base` + `mail`。具体 responder 由桥接 addon 接入。
5. **不碰 llm_discuss**：与 `llm_discuss` 是**并行接口层**关系。llm_discuss 继续
   专属服务 llm.agent，本 addon 先服务外部 agent-box；未来再收敛。

## 非目标（本阶段不做）

- 不实现任何具体 responder（`llm.agent` / `agenthub.agent` 的桥接是独立 addon）。
- 不实现 worker / cron 消费循环（消费方由桥接 addon 或外部运行时承担）。
- 不实现流式打字机输出、typing 指示、超时重放、GC——这些是 llm_discuss 已经
  验证过的可靠性细节，收敛阶段再迁入。
- 不实现 OdooBot 私聊接管。
