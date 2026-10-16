# 验收标准

每个功能点对应 `tests/` 中的测试用例，QC 以测试全绿为准。

| # | 功能点 | 验收标准 | 测试 |
|---|--------|----------|------|
| A1 | 同步解析 | mock 数据源后，`_sync_china_holidays(year)` 为每条 `days` 生成一条 `hr_holidays_china.day`，`kind` 正确区分 holiday/makeup | `test_sync_creates_days_and_leaves` |
| A2 | 放假落日历 | holiday 日期的 `leave_id.time_type == 'leave'`、`resource_id` 为空、`calendar_id` 指向目标日历 | `test_sync_creates_days_and_leaves` |
| A3 | 调休落日历 | makeup 日期的 `leave_id.time_type == 'other'` | `test_sync_creates_days_and_leaves` |
| A4 | 幂等 | 连续同步两次后，`day` 与关联 `leave` 数量不变（各 2 条） | `test_sync_is_idempotent` |
| A5 | 放假不工作 | 放假日期 `get_work_hours_count` 返回 0 | `test_holiday_is_not_working` |
| A6 | 调休上班 | 调休周末 `get_work_hours_count` 返回正常工作日时长（9 小时） | `test_makeup_day_is_working` |
| A7 | 普通日不受影响 | 普通工作日仍返回正常时长（9 小时） | `test_normal_weekday_still_working` |

## 装载与静态检查（QC 门禁）

- 模块干净装载：`-u hr_holidays_china --stop-after-init` 退出码 0。
- 所有改动的 XML 通过 `xml.dom.minidom` 解析。
- 测试不联网（`_fetch_china_holidays_json` 被 mock）。
