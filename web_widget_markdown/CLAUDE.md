# web_widget_markdown — 开发约束（自动加载）

设计文档见 `docs/`，这是唯一要求来源，改代码前先读：

- `docs/requirements.md` — 业务需求与边界
- `docs/design.md` — 架构、组件、关键取舍
- `docs/acceptance.md` — 验收标准（QC 唯一依据）

红线（来自 design.md，勿违背）：

1. 渲染的 markdown HTML 必须先过 DOMPurify 再 `markup()`，只走 `t-out`，绝不 `t-raw`。
2. 只支持 `text`/`char` 字段；解析器只能是 vendored 的 `marked`，不引入后端 Python 依赖。
