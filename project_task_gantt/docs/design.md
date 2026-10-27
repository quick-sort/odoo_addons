# Project Task Gantt — 设计

## 字段

| 字段 | 说明 |
|---|---|
| `task_start_date` | 唯一的存储日期：Gantt 开始时间，创建时默认当前时间 |
| `date_deadline` | 核心字段，Gantt 结束时间的唯一来源（不复制、不同步） |
| `gantt_duration` | 计算字段：`date_deadline` 与 `task_start_date` 相差的天数 |
| `gantt_date_start` / `gantt_date_stop` | `gantt.mixin` 提供的非存储别名，读写都落到上面两个真实字段 |
| `task_end_date` | **非存储**兼容别名（compute+inverse+search），指向 `date_deadline`；保留给已引用该字段的视图（如 `hbm_project`），不产生列 |

`_gantt_date_fields()` 返回 `("task_start_date", "date_deadline")`。别名由 mixin
负责 compute/inverse/search/default_get，本模块不再写任何日期同步逻辑；核心
`date_end`（进入关闭阶段时由 project 写入的实际完成时间）不被触碰。

## 迁移

`task_end_date` 已删除；升级时 `migrations/19.0.1.0.0/pre-migrate.py` 把仅存在于
旧列的值回填到 `date_deadline`，并重算 `gantt_duration`。旧数据库列保留但不再使用。

## 数据载荷

`get_gantt_data(domain, group_by)` 返回 `{groups, markers}`：

```
{
  groups: [{ id, name, tasks: [{
      id, name,
      start_date, end_date,
      progress, color, priority, description,
      parent_id,
      depth,
      assignees: [display_name, ...],
  }]}],
  markers: [{ date, label, color, description }],
}
```

- `groups` 与旧结构完全一致（DFS 前序 + `depth` 契约不变）；旧版直接返回数组的
  载荷仍被前端兼容（视为 `markers: []`）。
- `markers` 来自**当前任务 domain 所覆盖项目**的 milestone：
  `deadline` 非空即画线，`is_reached` 决定颜色（已达成为灰 `#adb5bd`，未达成为
  主色 `#71639e`）与说明（Reached / Unreached）。查询不走 sudo，遵守 milestone
  记录规则；不按 `project.project.allow_milestones` 过滤（关闭开关不会删除历史
  milestone，本图按「全部有 deadline 的 milestone」展示）。
- 无任务时返回 `{groups: [], markers: []}`；异常同样返回空结构。
- 只返回 `task_start_date` 非空的任务；`date_deadline` 可为空，前端按起始 + 1 天处理。
- `user_ids` 以 `assignees` 名称数组下发，供左侧列表展示。
- `progress` 为 0–100 百分比：`project.task.progress`（hr_timesheet）是「已耗小时 / 分配小时」
  的 0–1 比例，超配时可超过 1.0；`get_gantt_data` 在此统一换算成百分比后下发。超配时值可
  >100，前端进度条按 100% 截断显示，tooltip / CSV 保留真实值。
- 排序固定为 `sequence asc, id asc`，拖拽日期不会重排行。
- 分组值为空的任务归入 `Unassigned`。
- 分组支持 `project_id` / `user_ids` / `stage_id` / `priority` / `partner_id`。

## 树排序

`_order_task_tree` 在分组内按 DFS 前序展开：父任务在前、后代紧随其后，并写入
`depth`。父任务不在结果集内（被 domain 过滤）的任务按根任务处理（depth 0）。
前端据此绘制缩进与折叠箭头；折叠时按 depth 连续跳过后代，因此顺序是契约。

## 视图

- `views/project_task_gantt_views.xml`：`<gantt date_start="gantt_date_start"
  date_stop="gantt_date_stop"/>`，并挂到项目任务与全部任务 action。
- 表单只新增 Start Date 与 Duration；结束时间即核心 Deadline 字段，不重复展示。
- 实际绘制由 `web_gantt` 的自绘渲染器完成。

## 被否决的方案

- **为 Gantt 结束时间单独存字段（旧 `task_end_date`）**：与 `date_deadline` 完全
  冗余，还被迫双向同步并误写核心 `date_end`；改为 mixin 别名指向 `date_deadline`。
- **前端按 parent_id 自行排序**：跨分组、被过滤的父子关系容易出错，统一在后端
  产出带 depth 的确定性顺序。
