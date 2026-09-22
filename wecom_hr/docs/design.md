# wecom_hr — 系统设计

## 总体形态

`wecom_hr` 是 `wecom` 之上的映射层，不直接调企微 API、不新建业务模型：

```
企微通讯录 API
      │  (wecom.app.get_departments / get_users，复用 wecom)
      ▼
wecom.department / wecom.user   ← wecom 缓存（已存在）
      │  (wecom_hr 新增 sync_to_hr，映射层，不联网)
      ▼
hr.department / hr.employee     ← Odoo 标准 HR
```

同步编排（`wecom.app.sync_hr`）：

1. `sync_departments()` → 刷新 `wecom.department` 缓存（联网，复用 wecom）
2. `sync_users()` → 刷新 `wecom.user` 缓存（联网，复用 wecom）
3. 取该公司下缓存记录，先后调用 `wecom.department.sync_to_hr()`、`wecom.user.sync_to_hr()`

## 数据模型（全部 `_inherit`，不新建模型）

### hr.department（继承）

| 字段 | 类型 | 说明 |
|---|---|---|
| `wecom_id` | Integer (index) | 企微部门 ID，匹配键，按 `company_id` 隔离 |

### hr.employee（继承）

| 字段 | 类型 | 说明 |
|---|---|---|
| `wecom_userid` | Char (index) | 企微成员 UserId，匹配键，按 `company_id` 隔离 |

### 字段映射

| 企微字段 | Odoo 字段 | 转换 |
|---|---|---|
| `wecom.department.name` | `hr.department.name` | 原样 |
| `wecom.department.parent_id`（parentid） | `hr.department.parent_id` | 二遍按 `wecom_id` 解析 |
| `wecom.department.company_id` | `hr.department.company_id` | 原样 |
| `wecom.department.wecom_id` | `hr.department.wecom_id` | 原样 |
| `wecom.user.name` | `hr.employee.name` | 原样 |
| `wecom.user.position` | `hr.employee.job_title` | 原样 |
| `wecom.user.mobile` | `hr.employee.mobile_phone` | 原样 |
| `wecom.user.email` | `hr.employee.work_email` | 原样 |
| `wecom.user.gender` | `hr.employee.gender` | `'1'`→male，`'2'`→female，否则 other |
| `wecom.user.main_department` | `hr.employee.department_id` | 按 `hr.department.wecom_id` 解析 |
| `wecom.user.company_id` | `hr.employee.company_id` | 原样 |
| `wecom.user.wecom_id`（userid） | `hr.employee.wecom_userid` | 原样 |

## 同步算法（幂等）

### 部门 `wecom.department.sync_to_hr()`

对该公司 `wecom.department` 记录集：

1. 一遍：按 `(company_id, wecom_id)` 找 `hr.department`，有则 `write(name)`，无则入 `create` 队列；
   `create` 后回填映射表 `{wecom_id: hr.department}`。
2. 二遍：按 `parent_id`（企微 parentid）从映射表解析，写 `hr.department.parent_id`。

### 成员 `wecom.user.sync_to_hr()`

前置：部门已同步到 HR（`hr.department.wecom_id` 已就绪）。

1. 构建 `{wecom_id: hr.department.id}` 映射（查 `hr.department`，按 company 过滤）。
2. 对该公司 `wecom.user` 记录集，按 `(company_id, wecom_userid)` 找 `hr.employee`，有则 `write`、无则 `create`；
   字段按上表映射，`department_id` 由 `main_department` 的企微 ID 解析。

## 触发

- 手动：`wecom.app` 表单按钮「同步到HR」→ `action_sync_hr()`（返回 `display_notification`）。
- 定时：`ir.cron` 调用 `wecom.app._cron_sync_hr_all()`，遍历 `active` 应用逐个 `sync_hr()`。

## 权限

- 不新建业务模型，无需新增 `ir.model.access.csv`。
- `wecom.department` / `wecom.user` 的 ACL 沿用 `wecom`（仅 `base.group_system`）。
- `wecom.app` 表单本就 `base.group_system` 可见，按钮沿用；cron 以超管身份运行，可写 `hr.*`。

## 被否决的方案

| 方案 | 否决理由 |
|---|---|
| 直接读企微 API 写 `hr.*`，不落 `wecom.*` 缓存 | 重复造 `wecom` 已有的拉取与 token 缓存逻辑，且无法复用其幂等缓存。 |
| 成员匹配用手机/邮箱做唯一键 | 手机可空可多、邮箱可改，误配/漏配风险高；显式 `wecom_userid` 链接更稳。 |
| 同步时归档 Odoo 里不在企微的员工 | 误删风险高，单向同步阶段先「保留不动」，后续按需再加显式归档。 |
| 新建 `wecom_hr` 独立部门/人员模型，不接 `hr.*` | 无法进入 Odoo 组织架构/考勤/审批体系，失去 HR 集成价值。 |

## 明确的扩展点

- 头像下载、工号、多部门、部门负责人→经理、激活状态归档：需求已明确「不做」，未来在映射层
  `sync_to_hr()` 里按字段增量实现，不改动整体分层。
- 若要反向回写，单独在 `wecom.app` 上扩展「Odoo → 企微」方法，不与当前单向路径耦合。
