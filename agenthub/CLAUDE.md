# agenthub core — 开发约束（自动加载）

设计文档见 `docs/`，这是唯一要求来源，改代码前先读：

- `docs/requirements.md` — 业务需求与边界
- `docs/design.md` — 架构、模型、扩展点、被否决方案
- `docs/acceptance.md` — 验收标准（QC 唯一依据）

红线（勿违背）：

1. **core 只放抽象，不放任何具体 channel/agent。** 新增 channel 或 agent 只加
   独立 addon，用 `_inherit` 加字段、`selection_add` 加类型、component 提供
   实现；core 的 `channel_type`/`agent_type` 保持 `selection=[]`。
2. **channel 与 agent 互不依赖，由 `thread`/binding 运行时绑定。** 任何一边
   都不得 import 另一边的 addon；跨腿关联只走 `thread_key`、`turn_id` 以及
   `agenthub_external_id` / `agenthub_reply_to_external_id`。
3. **会话内容载体是 `mail.thread`，消息是 `mail.message`。** 不得另建
   `agenthub.message`；`agenthub.delivery` 只作 Odoo 侧审计副本，热队列与
   投递状态在 relay（见 `docs/design.md`）。
4. **core 不依赖 `llm`。** 需要 LLM 的 agent 实现把依赖封闭在它自己的 addon。
5. **Odoo 不在实时热路径。** 渠道长连接、路由、队列归 relay；Odoo 只做
   配置、Discuss UI、publish outbox、record feed 与归档。legacy 的 Odoo WS
   不得与 relay 同时持有同一个 `bot_id`。
