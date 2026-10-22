# Project Task Gantt — 验收标准

| # | 功能点 | 验收标准 | 测试 |
|---|---|---|---|
| AC1 | 树顺序 | 分组内任务为 DFS 前序：父任务先于子任务，`depth` 与层级一致 | `test_get_gantt_data_tree_order_and_depth` |
| AC2 | 稳定排序 | 顺序按 `sequence`，不受开始日期改动影响 | `test_order_follows_sequence_not_start_date`、`test_order_stable_when_dates_change` |
| AC3 | 被过滤的父任务 | 父任务不在结果集时，子任务按根任务处理（depth 0） | `test_subtask_with_parent_filtered_out_is_root` |
| AC4 | 负责人数据 | 任务分配用户后，载荷中的 `assignees` 为该用户的 display_name | `test_get_gantt_data_includes_assignees` |
| AC5 | 视图入口 | 项目任务与全部任务列表可切换到 Gantt 视图 | 人工检查 |
| AC6 | 折叠展示 | 有子任务的行显示箭头，点击后后代行隐藏/恢复 | 人工检查 |
| AC7 | Assignee 展示 | 左侧任务名右侧显示负责人名称 | 人工检查 |
| AC8 | 拖拽写回 | 拖动任务条后起止时间写回并落库 | 人工检查 |
| AC9 | 日期同步 | 表单修改 `task_end_date` 同步 `date_deadline`；修改 `date_deadline` 同步 `task_end_date` | 人工检查 |
