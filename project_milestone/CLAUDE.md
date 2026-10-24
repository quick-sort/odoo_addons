# project_milestone — 开发约束（自动加载）

设计文档见 `docs/`，这是唯一要求来源，改代码前先读：

- `docs/requirements.md` — 业务需求与边界
- `docs/design.md` — 架构与关键取舍
- `docs/acceptance.md` — 验收标准（QC 唯一依据）

红线（来自 design.md，勿违背）：
1. `last_task_deadline` 必须是 stored computed Date，取 `date_deadline` 最晚值，纯只读。
2. 不改动手工 `deadline` 字段的语义。
