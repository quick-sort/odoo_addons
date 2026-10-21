# Project Task Meetings — 设计

## 数据来源

不新增模型：会议就是 `calendar.event`，按 `res_model = 'project.task'` 且
`res_id in 项目任务 ids` 查询。

`calendar.event` 用多态引用 `res_model_id`（ir.model）+ `res_id` 指向文档；
`res_model` 是 `res_model_id.model` 的存储 related 字段。从任务创建「会议」活动，
或会议表单「文档」字段直接选任务，都会把 `res_model_id`/`res_id` 写回任务，
一遍查询即可。

## 入口

project 表单 `button_box` 加 `oe_stat_button`（`widget="statinfo"`），
`type="object"` 调 `project.project.action_view_task_meetings()`。

方法返回 `ir.actions.act_window`，`res_model = calendar.event`，默认日历视图
（`view_mode = "calendar,form"`），`domain` 由 `_get_task_meeting_domain()`
统一生成，`task_meeting_count` 用同一个 domain 的 `search_count`，避免两处
口径不一致。

## 任务视图入口（embedded action）

从项目进入任务视图后，Odoo 19 的 ControlPanel 通过 embedded actions 提供「Top Menu」
入口。新增一条 `ir.embedded.actions`（`views/embedded_actions.xml`）：

- `parent_action_id = project.act_project_project_2_project_task_all`（项目的任务 action）
- `parent_res_model = project.project`（可见性判断所针对的 active 记录模型）
- `python_method = action_view_task_meetings`（复用 smart button 的方法）
- `groups_ids = project.group_project_user`

不用 `action_id` 指向静态 act_window：目标 domain 依赖当前项目的任务 ids，
`calendar.event` 上没有 project_id 可 join，必须动态返回。

可见性由 `ir.embedded.actions.is_visible` 计算，要求 `context.active_id` 是当前用户
可访问的项目，否则按钮不出现；所以只在「从项目进入任务」时显示，从全局 All Tasks 菜单
进入时不显示。另外 embedded actions 不渲染在 form 视图，因此入口只出现在任务的
list/kanban/graph/pivot/activity 视图。

方法名沿用 `action_view_task_meetings`：ControlPanel 以 `parent_res_model` 为 resModel、
`active_id` 为 resId 调用 python_method，`self` 就是当前项目。

## 计算字段

`task_meeting_count` 非存储：会议随时间随时增删，缓存失效逻辑没有收益；
项目表单读取时查一次即可。

## 权限

- `self.task_ids` 以当前用户身份读取，受 `project.task` 记录规则约束，
  看不到的任务不会把会议带出来。
- `calendar.event` 对内部用户可读（`calendar` 的 ACL），无需新增 ACL 或规则。

## 只读

action context 设 `create/edit/delete = False`。汇总视图只用于浏览和打开会议，
会议的生命周期仍归属任务，避免在这里创建与任务脱钩的会议。

## 被否决的方案

- **改现有 project.task 日历视图**：`<calendar>` 只能渲染一个 model 的记录、
  每条记录按一个日期字段定位，无法把一条任务展开成多条会议。
- **任务列表加会议数量列**：只能看到计数，看不到会议本身，也无法按项目汇总。
