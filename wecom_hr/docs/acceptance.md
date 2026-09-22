# wecom_hr — 验收标准

> 这是 QC 的唯一依据。每个功能点（AC-x）必须有一个对应的测试；测试全绿才算通过。

## AC-1 部门创建

`wecom.department.sync_to_hr()` 把缓存部门建成 `hr.department`，写入 name / company_id / wecom_id。
— `test_department_sync_creates_and_parents`

## AC-2 部门层级

二遍映射把企微 `parentid` 解析成 `hr.department.parent_id`，层级正确。
— `test_department_sync_creates_and_parents`

## AC-3 部门幂等

重复同步只更新 name，不产生重复 `hr.department`。
— `test_department_sync_idempotent`

## AC-4 成员创建

`wecom.user.sync_to_hr()` 把缓存成员建成 `hr.employee`，写入
name / job_title / mobile_phone / work_email / department_id / company_id / wecom_userid。
— `test_employee_sync_creates_and_maps_department`

## AC-5 成员幂等

按 `(company_id, wecom_userid)` 匹配，重复同步不重复建人、只更新字段。
— `test_employee_sync_idempotent_matches_by_wecom_userid`

## AC-6 映射层离线

`sync_to_hr()` 只吃缓存记录，不触发网络；测试无需 mock 即可跑。
— 上述 `test_department_*` / `test_employee_*` 直接构造缓存记录调用，全程不 mock。

## AC-7 触发编排

`wecom.app.sync_hr()` 先刷新部门/成员缓存、再映射到 HR；`_cron_sync_hr_all()` 遍历 active 应用。
（网络调用通过 mock `get_wecom_client` 隔离。）
— `test_sync_hr_orchestrates`

## 运行方式

```bash
docker exec odoo odoo -c /etc/odoo/odoo.conf -d <db> -i wecom_hr \
    --test-enable --test-tags /wecom_hr --stop-after-init --workers=0 --no-http
```
