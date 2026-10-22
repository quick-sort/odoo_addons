# Project Task Gantt — 设计

## 字段

| 字段 | 说明 |
|---|---|
| `task_start_date` | Gantt 起始时间，创建时默认当前时间 |
| `task_end_date` | Gantt 结束时间 |
| `gantt_duration` | 计算字段：结束与起始相差的天数 |

`create` / `write` 中同步：`task_start_date` ↔ `date_start`，
`task_end_date` ↔ `date_deadline` ↔ `date_end`（存在时），保留具体时分秒。
同步只在模型层做，前端直接写 `task_start_date` / `task_end_date`。

## 数据载荷

`get_gantt_data(domain, group_by)` 返回按分组聚合的列表：

```
[{ id, name, tasks: [{
    id, name,
    start_date, end_date,
    progress, color, priority, description,
    parent_id,
    depth,
    assignees: [display_name, ...],
}]}]
```

- 只返回 `task_start_date` 非空的任务；`task_end_date` 可为空，前端按起始 + 1 天处理。
- `user_ids` 以 `assignees` 名称数组下发，供左侧列表展示。
- 排序固定为 `sequence asc, id asc`，拖拽日期不会重排行。
- 分组值为空的任务归入 `Unassigned`。
- 分组支持 `project_id` / `user_ids` / `stage_id` / `priority` / `partner_id`。

## 树排序

`_order_task_tree` 在分组内按 DFS 前序展开：父任务在前、后代紧随其后，并写入
`depth`。父任务不在结果集内（被 domain 过滤）的任务按根任务处理（depth 0）。
前端据此绘制缩进与折叠箭头；折叠时按 depth 连续跳过后代，因此顺序是契约。

## 视图

- `views/project_task_gantt_views.xml`：`<gantt date_start="task_start_date"
  date_stop="task_end_date"/>`，并挂到项目任务与全部任务 action。
- 实际绘制由 `web_gantt` 的自绘渲染器完成。

## 被否决的方案

- **用 `date_start`/`date_deadline` 直接作为 Gantt 字段**：`date_deadline` 可空且
  语义是截止日，与 Gantt 结束时间不完全等价；单独字段便于用户维护。
- **前端按 parent_id 自行排序**：跨分组、被过滤的父子关系容易出错，统一在后端
  产出带 depth 的确定性顺序。
