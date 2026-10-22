# Project Task Gantt — 需求

## 问题

项目任务需要按时间轴查看：哪些任务在什么时候进行、由谁负责、父子任务关系如何。
社区版没有可用的任务 Gantt 视图。

## 范围

- 为 `project.task` 提供 Gantt 视图，起止字段为 `task_start_date` /
  `task_end_date`，并注册到项目任务与全部任务两个 action。
- 左侧列表按 `parent_id` 展示父子层级；有子任务的行可由用户折叠/展开。
- 任务名右侧显示负责人（`user_ids`）。
- 支持按项目、负责人、阶段、优先级分组。
- 任务表单可维护 Gantt 起止日期，并与 `date_deadline` / `date_start` 保持同步。
- 拖拽改期写回 `task_start_date` / `task_end_date`。

## 不做

- 不新增任务模型或并行日期字段；只复用现有 `project.task`。
- 不做自动排期（自动排期属于 `project_task_plan`）。
- 不改变任务列表/看板的排序规则。
