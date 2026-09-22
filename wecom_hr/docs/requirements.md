# wecom_hr — 业务需求

## 要解决的问题

`wecom` 模块已经能拉取企业微信通讯录，并缓存到 `wecom.department` / `wecom.user`。
但这两张表只是「企微原始数据的镜像」，没有进入 Odoo 的 HR 体系。

Odoo 的 HR（`hr.department` / `hr.employee`）才是人事数据的落点：考勤、审批、组织架构、
权限都要挂在员工上。手动维护两套组织/人员既重复又易错。

本模块把企微通讯录缓存**单向映射**进 Odoo HR，让企微成为部门与成员数据的事实来源。

## 范围

### 做

- 把 `wecom.department` 同步为 `hr.department`（含上下级层级）。
- 把 `wecom.user` 同步为 `hr.employee`（含姓名、职位、手机、邮箱、性别、主部门、公司）。
- 成员以 `hr.employee.wecom_userid` 为匹配键，重复同步只更新、不重复建人。
- 部门以 `hr.department.wecom_id` 为匹配键，重复同步只更新、不重复建部门。
- 同步触发：`wecom.app` 表单「同步到HR」按钮 + 定时任务 `ir.cron`。

### 不做

- **头像下载**：企微 `avatar` 是 URL，不下载成 `image_1920`。
- **工号**：`hr.employee` 无标准「工号」字段，`job_number` 不映射。
- **多部门**：企微成员可属多部门，但 `hr.employee.department_id` 是单值，只取「主部门」。
- **部门负责人 → 经理**：`department_leader` 不映射成 `hr.department.manager_id` / `hr.employee.parent_id`。
- **激活状态归档**：企微 `status`（禁用/退出）不反向归档 Odoo 员工。
- **反向回写**：Odoo 里的改动不回写企微（单向）。
- **删除/归档不在企微的人**：Odoo 里存在但企微通讯录里没有的员工**保留不动**。

## 非功能要求

1. 同步逻辑分层：映射层（`sync_to_hr`）只吃缓存记录、不联网，可离线单测。
2. 同步幂等：重复执行不产生重复数据。
3. 多公司隔离：匹配与同步都按 `company_id` 隔离，一个 Odoo 库可对接多个企微主体。
4. 复用 `wecom` 既有接口，不在本模块直接 import `wechatpy`。
