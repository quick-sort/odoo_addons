# Project Task Activities — 验收标准

| # | 功能点 | 验收标准 | 测试 |
|---|---|---|---|
| AC1 | 数量统计 | 项目表单显示的活动数等于该项目所有任务关联活动数之和 | `test_count_includes_task_activities` |
| AC2 | 项目隔离 | 其他项目的任务关联活动不计入当前项目 | `test_count_excludes_other_projects` |
| AC3 | 模型隔离 | 挂在非任务记录上的活动不计入 | `test_count_excludes_activities_linked_to_other_models` |
| AC4 | 视图范围 | action 的 domain 只包含本项目任务的活动，不包含其他项目 | `test_action_domain_is_scoped_to_project_tasks` |
| AC5 | 只读 | action 的 context 禁止 create/edit/delete | 人工检查（`action_view_task_activities`） |
| AC6 | 项目隔离（UI） | 从项目表单打开列表只看到本项目任务关联活动 | 人工检查 |
| AC7 | 任务视图入口 | 从项目进入任务视图，Top Menu 中有 Activities；active_id 非项目时不显示 | `test_embedded_action_in_project_task_action` |
| AC8 | 入口一致性 | 任务视图入口打开与 smart button 相同的活动列表（同一方法） | 代码审查（共用 `action_view_task_activities`） |
