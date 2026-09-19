# InfoHub core — 开发约束（自动加载）

设计文档见 `docs/`，这是唯一要求来源，改代码前先读：

- `docs/requirements.md` — 业务需求与边界
- `docs/design.md` — 架构、模型、扩展点、被否决的方案
- `docs/acceptance.md` — 验收标准（QC 唯一依据）

红线（勿违背）：

1. **core 不预置渠道专属字段，不依赖 llm。** 新增渠道只加独立 addon，用
   `_inherit` 加字段、`selection_add` 加类型、component 提供 fetch/content。
2. **出网必须走 `url_guard`**，手工逐跳重定向校验，禁止 `allow_redirects=True`
   或裸 `requests.get`。
3. **失败簿记走独立 cursor**，否则会被 queue_job 回滚吞掉。
