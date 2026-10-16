# hr_holidays_china — 开发约束（自动加载）

设计文档见 `docs/`，这是唯一要求来源，改代码前先读：

- `docs/requirements.md` — 业务需求与边界
- `docs/design.md` — 架构、模型、扩展点、被否决的方案
- `docs/acceptance.md` — 验收标准（QC 唯一依据）

红线（来自 design.md，勿违背）：

1. 放假/调休都必须落在公司级 `resource.calendar.leaves`（`resource_id=False`），
   不新建平行的"节假日"模型去重复表达日历。
2. 调休补班通过覆盖 `resource.calendar._attendance_intervals_batch` 注入工时，
   不得改动 `resource` 核心模块本体。
3. 同步必须幂等（按 `company_id + date` 唯一），重复运行不产生重复记录。
4. 测试不得联网：`_fetch_china_holidays_json` 必须被 mock。
