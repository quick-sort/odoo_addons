# project_activity_notify — 开发约束（自动加载）

设计文档见 `docs/`，这是唯一要求来源，改代码前先读：

- `docs/requirements.md` — 业务需求与边界
- `docs/design.md` — 架构与关键取舍
- `docs/acceptance.md` — 验收标准（QC 唯一依据）

红线（来自 design.md，勿违背）：
1. 提醒必须复用 `mail.activity.action_notify()`（与创建通知同内容），不另写邮件模板。
2. 每个 activity 只提醒一次，`reminder_sent` 不随 `date_deadline` 变化重置。
