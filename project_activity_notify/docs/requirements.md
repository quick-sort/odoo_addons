# Requirements

## 背景

项目上有各种挂在任务或项目本身上的 activity，带一个到期日 `date_deadline`。用户希望
在到期前若干天发邮件提醒，提醒内容与「创建 activity 时发出的通知」一致，且每个
activity 只提醒一次。

## 需求

1. 在 `project.project` 上增加一个整数配置 `activity_reminder_days`（提前提醒天数，
   0 或空 = 关闭）。
2. 每天定时扫描：对配置了天数的项目，找出「任务(project.task) 和项目(project.project)
   上、到期日正好 = 今天 + N 天、尚未提醒过」的 activity，发送提醒邮件。
3. 提醒邮件内容 = 创建 activity 时的通知（复用 `mail.activity.action_notify()`）。
4. 每个 activity 只提醒一次（用 `reminder_sent` 标记）。

## 边界（不做）

- 不改动 activity 创建时的通知逻辑本身。
- 不支持在 activity 级别单独关闭/开启提醒（统一按所属项目配置）。
- 不支持多次提醒或 reschedule 后重新提醒。
