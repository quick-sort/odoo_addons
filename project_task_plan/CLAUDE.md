# project_task_plan — 开发约束（自动加载）

设计文档见 `docs/`，这是唯一要求来源，改代码前先读：

- `docs/requirements.md` — 业务需求与边界
- `docs/design.md` — 架构、模型、传播规则、被否决的方案
- `docs/acceptance.md` — 验收标准（QC 唯一依据，AC-01~AC-19）

红线（来自 design.md，勿违背）：

1. 不改核心 `project` / `project_task_gantt` 的字段语义，全部 `_inherit` 扩展。
2. 排期传播必须幂等、可重入安全（context 标记 `_auto_schedule_guard` 防递归）。
3. 后置任务开始时间严格取前置结束时间的最大值，不额外增加偏移。
