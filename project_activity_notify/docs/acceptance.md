# Acceptance

每个功能点对应 `tests/` 里至少一条用例。

1. 任务和项目本身的 activity，到期日 = 今天 + N 天时会被提醒（`reminder_sent` 置真）。
2. 到期日不是今天 + N 天时不被提醒。
3. `activity_reminder_days = 0` 的项目不提醒。
4. 同一 activity 只提醒一次（重复跑 cron 不再触发）。
5. 模块干净装载（`-u project_activity_notify` 退出码 0）。
