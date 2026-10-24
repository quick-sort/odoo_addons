# Design

## 方案

继承 `project.milestone`，新增一个 stored computed Date 字段
`last_task_deadline`：

- `compute='_compute_last_task_deadline'`，`store=True`。
- `@api.depends('task_ids.date_deadline')`：任务 deadline 变化，或任务被加进/移出
  该里程碑（`milestone_id` 反向依赖）时触发重算。
- 计算用一次 `_read_group`（`date_deadline:max` 按 milestone 分组），避免对每个
  里程碑循环发 N+1 查询。

## 关键取舍

- **stored** 而非 non-stored：让字段可在列表视图排序/分组/筛选，且与核心
  `reached_date` 的处理方式一致。
- **取 `date_deadline` 的日期部分**：字段类型是 Date，与手工 `deadline` 对齐；
  丢失的时间精度对里程碑日期无意义。

## 被否决的方案

- 用 `date_end`（实际结束）而非 `date_deadline`（计划截止）：需求明确取计划截止。
