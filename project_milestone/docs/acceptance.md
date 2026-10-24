# Acceptance

每个功能点对应 `tests/` 里至少一条用例。

1. `last_task_deadline` 等于任务中最晚的 `date_deadline`（取日期）。
2. 无 `date_deadline` 的任务被忽略。
3. 全部任务无 `date_deadline` 时字段为空。
4. 无任务时字段为空。
5. 任务 `date_deadline` 变更后字段重算。
6. 模块干净装载（`-u project_milestone` 退出码 0）。
