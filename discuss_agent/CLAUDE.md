# discuss_agent — 开发约束（自动加载）

设计文档见 `docs/`，这是唯一要求来源，改代码前先读：

- `docs/requirements.md` — 业务需求与边界
- `docs/design.md` — 架构、多态方案、接口契约、被否决方案
- `docs/acceptance.md` — 验收标准（QC 唯一依据）

红线（来自 design.md，勿违背）：

1. **core 只放接口/抽象**，不 import `llm`、不 import `agenthub`，依赖仅
   `base` + `mail`。具体 responder 由桥接 addon 用 `selection_add` +
   `_discuss_execute` 协议方法接入。
2. **回复人格 ≠ 执行身份**：`source_user_id`（用谁的权限执行）与
   `reply_partner_id`（谁的名义回）分离，入队固化；`sudo` 只用于发帖，绝不
   传给工具。
3. **触发/入队绝不阻塞用户发消息**：dispatch 用 try/except 包裹，任何 agent
   失败都不得回滚用户已发出的消息。
4. **不碰 llm_discuss**（并行接口层）。
