# Design

## 方案

- `project.project` 加 `activity_reminder_days`（Integer，默认 0）。
- `mail.activity` 加 `reminder_sent`（Boolean，默认 False，copy=False）作为去重标记。
- 一个每日 `ir.cron` 调用 `mail.activity._cron_remind_activities()`：
  - 遍历 `activity_reminder_days > 0` 的项目；
  - 目标日期 = 今天 + N 天；
  - 查该项目下 project.project / project.task 上、`active`、`reminder_sent=False`、
    `date_deadline == 目标日期` 的 activity；
  - 对每条调用 `action_notify()`（复用创建时的通知，内容/收件人/标题一致），
    再置 `reminder_sent=True`。

## 关键取舍

- **复用 `action_notify()`**：它正是「创建 activity 时通知负责人」的方法，渲染
  `mail.message_activity_assigned` 模板并 `message_notify`，保证内容一致。
- **精确匹配到期前 N 天**（`date_deadline == today + N`）：语义清晰；配合每日 cron
  与 `reminder_sent` 去重，不会重复提醒。
- **`reminder_sent` 不随 `date_deadline` 变化重置**：需求是「只提醒一次」。

## 被否决的方案

- 按 activity 类型或用户单独配置：需求只要求项目级配置，保持简单。
- 用 `date_deadline <= today + N` 的宽窗口：会导致提前更多天提醒，语义偏离
  「到期前几天」。
