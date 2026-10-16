# 设计

## 数据模型

### `hr_holidays_china.day`（新增）

导入后的每一天一条记录，是"该日期是什么"的单一事实来源：

- `name`：节假日名称（如"劳动节"）或"调休"。
- `date`：日期。
- `kind`：`holiday`（放假）| `makeup`（调休补班）。
- `year`：所属安排年份。
- `company_id`：归属公司。
- `leave_id`：生成的 `resource.calendar.leaves`。

唯一约束：`(company_id, date)`。

### `resource.calendar.leaves`（继承）

新增反向字段 `china_holiday_day_id`，用于把日历 leave 关联回 `day`，也让
日历计算能识别哪些 leave 是调休补班。

### `res.company`（继承）

- `hr_holidays_china_calendar_id`：写入的目标日历（空则用公司默认日历）。
- `hr_holidays_china_auto_update`：是否参与定时自动更新。

数据源 URL 存于系统参数 `hr_holidays_china.url_template`（默认 holiday-cn）。

## 映射到 Odoo 原生语义

Odoo 里"公司级公休日"的原生表示是 `resource.calendar.leaves`，且
`resource_id` 为空。`hr_holidays` 的「Public Time Off」界面正是如此过滤。

- **放假** → `resource.calendar.leaves(time_type='leave')`。`_work_intervals_batch`
  默认 `attendance - leave`，工作日被正确扣成非工作日。
- **调休补班** → `resource.calendar.leaves(time_type='other')` 作为标记，
  再通过覆盖 `resource.calendar._attendance_intervals_batch` 把这些日期作为
  额外 attendance 注入（见下）。

## 调休补班的工时注入

`resource.calendar` 的 `_attendance_intervals_batch` 只从每周 `attendance_ids`
生成工时，无法表达"某个周末上班"的一次性例外。本模块覆盖该方法：在正常
attendance 之外，把落在查询区间内的调休日按该日历**周一**的班次模板注入为
工时区间。

- 模板取周一（`dayofweek='0'`）的 `attendance_ids`（排除 lunch）；无周一
  班次时退化为该日历全部班次。
- 只注入 `time_type='other'` 且 `china_holiday_day_id` 非空的 leave，避免
  误伤其他模块创建的 `other` 类型 leave。
- `lunch=True` 时直接跳过，避免污染午餐区间计算。

选择覆盖 `_attendance_intervals_batch` 而非 `_work_intervals_batch`，是因为
前者是所有工时计算的底层漏斗（`_work_intervals_batch`、`hr_work_entry`、
`hr_attendance` 等都直接调用它），覆盖一处即覆盖全部。

## 公休日时区转换的绕过

`hr_holidays` 覆盖了 `resource.calendar.leaves.create`，对公休日（`resource_id`
为空）的 `date_from`/`date_to` 执行 `_prepare_public_holidays_values`：把它从
用户时区转换到日历时区。本模块写入的已经是 UTC 值，会被该转换二次偏移。
因此覆盖 `_prepare_public_holidays_values`，对带 `china_holiday_day_id` 的记录
跳过转换，其余公休日（UI 手工录入）仍走原逻辑。

## 同步流程

1. `_sync_china_holidays(year)`：拉取 JSON → 逐条解析。
2. 按 `(company_id, date)` upsert `day`。
3. 对每个 `day` 调用 `_ensure_calendar_leave`：创建或更新对应的
   `resource.calendar.leaves`（放假 `leave` / 调休 `other`）。
4. 幂等：已存在则 `write` 相同值，不新建。

拉取用 `requests`（https 校验 + 30s 超时 + 5MB 上限）。数据源是管理员配置的
系统参数而非用户输入，故不做逐请求 SSRF 防护，但强制 https。

定时任务 `ir.cron` 每月跑一次 `_cron_sync_china_holidays`，同步当前年 + 下一年
（官方通知每年 11 月左右发布下一年安排）。

## 被否决的方案

- **新建独立"节假日"业务模型并让各处显式引用**：与 Odoo 原生
  `resource.calendar.leaves` 双写，产生两处真相，且无法让既有排程/工时逻辑
  自动生效。否决。
- **为调休日在 `resource.calendar.attendance` 里造一次性记录**：`attendance`
  是每周循环模型，无日期维度，无法表达一次性例外。否决。
- **只处理放假、忽略调休**：会让调休周末被错算成休息日，工时/排产错误。否决。

## 约束（红线）

1. 放假/调休统一落在 `resource.calendar.leaves`，不另建平行模型。
2. 覆盖 `resource.calendar._attendance_intervals_batch` 与
   `resource.calendar.leaves._prepare_public_holidays_values`，不改 `resource`/`hr_holidays` 本体。
3. 同步幂等。
4. 测试不联网。
