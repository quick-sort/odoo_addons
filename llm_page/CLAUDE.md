# llm_page — 开发约束（自动加载）

设计文档见 `docs/`，这是唯一要求来源，改代码前先读：

- `docs/requirements.md` — 业务需求与边界
- `docs/design.md` — 架构、模型、扩展点、被否决的方案
- `docs/acceptance.md` — 验收标准（QC 唯一依据）

红线（来自 design.md，勿违背）：

1. `llm.page.html` 是**原始 HTML**（`fields.Text`，不 sanitize），渲染用
   `Markup(page.html)` + `t-out`（非 `t-raw`）。安全由「审核员放行 + 指定用户组
   访问」双闸门兜底，绝不能把访问组默认指向过宽人群。
2. 只有 `llm_page.group_reviewer` 能 `approve` / `reject` / `unpublish`，由模型
   方法内部校验，不依赖视图按钮显隐。
3. agent 的 MCP 工具（`llm_page_*`）**不能指定 `group_id`**——访问组调整是
   审核员在后台的操作。
