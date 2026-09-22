=========
 WeCom HR
=========

把企业微信通讯录的「部门 + 成员」单向同步为 Odoo 标准 HR 模型
（``hr.department`` / ``hr.employee``），让企微成为组织与人员数据的事实来源。

依赖 ``wecom`` 提供的通讯录缓存（``wecom.department`` / ``wecom.user``）与拉取接口，
本模块只做「缓存 → HR」的映射，不直接调用企业微信 API。

工作方式
========

- 部门：``wecom.department`` → ``hr.department``，含上下级层级。
- 成员：``wecom.user`` → ``hr.employee``，含姓名、职位、手机、邮箱、性别、主部门、公司。
- 去重：成员按 ``hr.employee.wecom_userid``、部门按 ``hr.department.wecom_id`` 匹配，
  重复同步只更新、不重复建。
- 方向：单向（企微为准）；Odoo 里不在企微的员工保留不动。

安装
====

- 依赖：``wecom``、``hr``（标准 Odoo 模块）。
- 安装后，``wecom.app`` 表单会出现「同步到HR」按钮，并注册一个定时同步的 ``ir.cron``。

配置
====

1. 在「企微应用」里配好 CorpId / AgentId / Secret，且应用具备通讯录读取权限。
2. 点「同步到HR」，或等待定时任务自动同步。

安全
====

同步以点击用户（``base.group_system``）或定时任务（超管）身份运行；
``hr.*`` 的写权限沿用 Odoo HR 标准 ACL。

详细设计见 ``docs/``。
