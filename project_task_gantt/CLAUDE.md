# project_task_gantt — 开发约束（自动加载）

设计文档见 `docs/`，这是唯一要求来源，改代码前先读：

- `docs/requirements.md` — 业务需求与边界
- `docs/design.md` — 字段、数据载荷、树排序
- `docs/acceptance.md` — 验收标准（QC 唯一依据）

红线（来自 design.md，勿违背）：

1. `get_gantt_data` 返回的任务数组必须是 DFS 前序并带 `depth`；前端折叠逻辑依赖该顺序，禁止改成按日期排序。
2. Gantt 日期只经 `gantt.mixin` 别名读写：开始落 `task_start_date`，结束落核心 `date_deadline`；不得新增结束日期存储字段，也不得改动核心 `date_end`（实际完成时间）。
