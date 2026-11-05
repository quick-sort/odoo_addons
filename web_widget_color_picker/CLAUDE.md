# web_widget_color_picker — 开发约束（自动加载）

设计文档见 `docs/`，这是唯一要求来源，改代码前先读：

- `docs/requirements.md` — 业务需求与边界
- `docs/design.md` — 架构、组件、关键取舍
- `docs/acceptance.md` — 验收标准（QC 唯一依据）

红线（来自 design.md，勿违背）：

1. 不得占用核心 widget 名 `color_picker` / `kanban_color_picker`；
   本模块只注册 `compact_color_picker`。
2. 选中颜色必须 `record.update(..., {save: true})`，否则列表里不落库。
