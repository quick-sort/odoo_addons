# wechat — 开发约束（自动加载）

设计文档见 `docs/`，这是唯一要求来源，改代码前先读：

- `docs/requirements.md` — 业务需求与边界（含明确不做清单）
- `docs/design.md` — 架构、模型、API 网关、被否决方案
- `docs/acceptance.md` — 验收标准（QC 唯一依据）

红线（来自 design.md，勿违背）：

1. 所有微信 API 出站调用必须经 `wechat.request`（models/wechat_request.py），
   禁止直接拼 access_token 发 HTTP。
2. 回调被动回复只能通过 `_process_payload` 的 payload-dict 协议返回
   （controllers/mp_callback.py），处理器不得自行构造 HTTP 响应。
