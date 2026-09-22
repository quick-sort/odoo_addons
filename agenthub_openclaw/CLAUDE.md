# agenthub_openclaw — 开发约束（自动加载）

设计文档见 `docs/`，这是唯一要求来源，改代码前先读：

- `docs/requirements.md` — 业务需求与边界
- `docs/design.md` — 对话语义、流式累积、解耦边界
- `docs/acceptance.md` — 验收标准（QC 唯一依据）

红线（勿违背）：

1. **只做语义，不做传输。** 本 addon 不得 import 任何具体 channel addon
   （尤其 `agenthub_wecom`），只操作 `mail.message` 的字段（含 `agenthub_*`）。
2. **关联只走 `agenthub_reply_to_external_id` / `agenthub_external_id`**，由
   core 路由 + channel 归一化填好，agent 只消费。
3. **`<think>` 与正文分离**，正文 markdown 原样保留，不做破坏性改写。
