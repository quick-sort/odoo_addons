# agenthub core — 开发约束（自动加载）

设计文档见 `docs/`，这是唯一要求来源，改代码前先读：

- `docs/requirements.md` — 业务需求与边界
- `docs/design.md` — 架构、模型、扩展点、被否决方案
- `docs/acceptance.md` — 验收标准（QC 唯一依据）

红线（勿违背）：

1. **core 只放抽象，不放任何具体 channel/agent。** 新增 channel 或 agent 只加
   独立 addon，用 `_inherit` 加字段、`selection_add` 加类型、component 提供
   实现；core 的 `channel_type`/`agent_type` 保持 `selection=[]`。
2. **channel 与 agent 互不依赖，由 `thread` 运行时绑定。** 任何一边都不得
   import 另一边的 addon；关联只走 `agenthub_external_id` /
   `agenthub_reply_to_external_id`。
3. **会话载体是 `mail.thread`，消息是 `mail.message`。** 不得另建
   `agenthub.message` 或 delivery 表；投递状态用 `agenthub_delivery_state`。
4. **core 不依赖 `llm`。** 需要 LLM 的 agent 实现把依赖封闭在它自己的 addon。
