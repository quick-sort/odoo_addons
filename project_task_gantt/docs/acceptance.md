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
| AC8 | 拖拽写回 | 拖动任务条后 `task_start_date` / `date_deadline` 写回并落库 | `test_gantt_alias_write_updates_backing_fields`、人工检查 |
| AC9 | 别名读取 | `gantt_date_start` / `gantt_date_stop` 分别读到 `task_start_date` / `date_deadline` | `test_gantt_alias_reads_backing_fields` |
| AC10 | 不污染完成时间 | 写别名或 `date_deadline` 不修改核心 `date_end` | `test_gantt_alias_write_leaves_date_end_untouched` |
| AC11 | 表单双向 | 修改 `date_deadline` 后别名读到新值 | `test_date_deadline_write_shows_in_gantt_stop` |
| AC12 | 别名可搜索 | 对 `gantt_date_start` / `gantt_date_stop` 的 domain 等价于后端字段 | `test_search_on_gantt_date_aliases` |
| AC13 | 新建默认值 | Gantt 的 New 把当天映射到 `task_start_date`，别名不进入默认值 | `test_default_get_maps_gantt_start_to_backing_field`、`test_explicit_backing_default_wins_over_alias` |
| AC14 | 载荷结束值 | `get_gantt_data` 的 `end_date` 来自 `date_deadline` | `test_get_gantt_data_end_date_uses_deadline` |
| AC15 | 兼容别名 | `task_end_date` 为非存储字段，读写/搜索都落到 `date_deadline` | `test_task_end_date_is_compat_alias_of_deadline` |
| AC16 | 载荷结构 | `get_gantt_data` 返回 `{groups, markers}`；无任务/异常时返回空结构 | `test_get_gantt_data_returns_groups_and_markers`、`test_markers_empty_when_no_tasks` |
| AC17 | 标记来源 | 域内项目的 milestone（有 deadline）生成 marker，日期为 `YYYY-MM-DD` | `test_markers_include_milestones_with_deadline` |
| AC18 | 标记过滤 | 无 deadline 的 milestone、域外项目的 milestone、无项目任务不产生 marker | `test_markers_exclude_milestone_without_deadline`、`test_markers_exclude_milestones_of_projects_outside_domain`、`test_markers_empty_for_private_task_without_project` |
| AC19 | 标记状态 | 已达成为灰 `#adb5bd` / Reached，未达成为主色 `#71639e` / Unreached | `test_marker_color_and_description_reflect_is_reached` |
| AC20 | 分组无关与去重 | 按 user 等非 project 分组时仍返回 marker；多分组/多任务不重复 | `test_markers_are_project_scoped_when_grouping_by_user`、`test_markers_not_duplicated_for_multi_group_tasks` |
| AC21 | 进度百分比 | `get_gantt_data` 的 `progress` 为 0–100 百分比（由 hr_timesheet 的 0–1 比例换算，超配可 >100） | `test_gantt_progress_pct_converts_ratio_to_percentage` |
