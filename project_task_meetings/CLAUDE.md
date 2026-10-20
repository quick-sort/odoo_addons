# project_task_meetings — 开发约束（自动加载）

设计文档见 `docs/`，这是唯一要求来源，改代码前先读：

- `docs/requirements.md` — 业务需求与边界
- `docs/design.md` — 架构、数据来源、被否决的方案
- `docs/acceptance.md` — 验收标准（QC 唯一依据）

红线（来自 design.md，勿违背）：

1. 不新增会议模型；数据来源必须是 `calendar.event`（`res_model='project.task'`）。
2. 数量与视图必须共用 `_get_task_meeting_domain()`，禁止两处各写一份 domain。
