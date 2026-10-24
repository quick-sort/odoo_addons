# Project Task Gantt — 需求

## 问题

项目任务需要按时间轴查看：哪些任务在什么时候进行、由谁负责、父子任务关系如何。
社区版没有可用的任务 Gantt 视图。

## 范围

- 为 `project.task` 提供 Gantt 视图：开始 = `task_start_date`（唯一的存储日期），
  结束 = 核心 `date_deadline`；两者经 `web_gantt` 的 `gantt.mixin` 暴露为
  `gantt_date_start` / `gantt_date_stop`。注册到项目任务与全部任务两个 action。
- 左侧列表按 `parent_id` 展示父子层级；有子任务的行可由用户折叠/展开。
- 任务名右侧显示负责人（`user_ids`）。
- 支持按项目、负责人、阶段、优先级分组。
- 任务表单可维护 Start Date 与 Deadline；两者双向反映到 Gantt。
- 拖拽改期写回 `task_start_date` / `date_deadline`。
- Gantt 上以竖向标记线展示域内任务所属项目的 milestone deadline：全部有 deadline
  的 milestone 都显示，已达成为灰色、未达成为主色，标签常显并可悬停查看详情。

## 不做

- 不为 Gantt 结束时间新增存储字段，也不改动核心 `date_end`（实际完成时间）。
- 不新增任务模型或并行日期字段；只复用现有 `project.task`。
- 不做自动排期（自动排期属于 `project_task_plan`）。
- 不改变任务列表/看板的排序规则。
