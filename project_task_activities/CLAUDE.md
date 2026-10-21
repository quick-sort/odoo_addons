# project_task_activities — 开发约束（自动加载）

设计文档见 `docs/`，这是唯一要求来源，改代码前先读：

- `docs/requirements.md` — 业务需求与边界
- `docs/design.md` — 架构、数据来源、被否决的方案
- `docs/acceptance.md` — 验收标准（QC 唯一依据）

红线（来自 design.md，勿违背）：

1. 不新增活动模型；数据来源必须是 `mail.activity`（`res_model='project.task'`）。
2. 数量与列表必须共用 `_get_task_activity_domain()`，禁止两处各写一份 domain。
