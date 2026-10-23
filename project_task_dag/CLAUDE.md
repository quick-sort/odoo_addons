# project_task_dag — 开发约束（自动加载）

设计文档见 `docs/`，这是唯一要求来源，改代码前先读：

- `docs/requirements.md` — 业务需求与边界
- `docs/design.md` — 两模块架构、数据契约
- `docs/acceptance.md` — 验收标准（QC 唯一依据）

红线（来自 design.md，勿违背）：
1. `get_dag_data` 必须是 `@api.model`，边只保留两端都在 recordset 内的。
2. 前端不放在本模块：渲染在 `web_dag`，本模块只供数据源与视图 wiring。
