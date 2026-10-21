# Project Task Activities — 设计

## 数据来源

不新增模型：活动就是 `mail.activity`，按 `res_model = 'project.task'` 且
`res_id in 项目任务 ids` 查询。

`mail.activity` 用多态引用 `res_model_id`（ir.model）+ `res_id` 指向被挂记录；
`res_model` 是 `res_model_id.model` 的存储 related 字段。任务上的活动（无论
来自活动面板、`activity_schedule` 还是 `mail.activity.mixin`）都会把
`res_model_id`/`res_id` 写回任务，一遍查询即可。

## 入口

project 表单 `button_box` 加 `oe_stat_button`（`widget="statinfo"`），
`type="object"` 调 `project.project.action_view_task_activities()`。

方法返回 `ir.actions.act_window`，`res_model = mail.activity`，
`domain` 由 `_get_task_activity_domain()` 统一生成，`task_activity_count`
用同一个 domain 的 `search_count`，避免两处口径不一致。

## 任务视图入口（embedded action）

从项目进入任务视图后，Odoo 19 的 ControlPanel 通过 embedded actions 提供「Top Menu」
入口。新增一条 `ir.embedded.actions`（`views/embedded_actions.xml`）：

- `parent_action_id = project.act_project_project_2_project_task_all`（项目的任务 action）
- `parent_res_model = project.project`（可见性判断所针对的 active 记录模型）
- `python_method = action_view_task_activities`（复用 smart button 的方法）
- `groups_ids = project.group_project_user`

不用 `action_id` 指向静态 act_window：目标 domain 依赖当前项目的任务 ids，
`mail.activity` 上没有 project_id 可 join，必须动态返回。

可见性由 `ir.embedded.actions.is_visible` 计算，要求 `context.active_id` 是当前用户
可访问的项目，否则按钮不出现；所以只在「从项目进入任务」时显示，从全局 All Tasks 菜单
进入时不显示。另外 embedded actions 不渲染在 form 视图，因此入口只出现在任务的
list/kanban/graph/pivot/activity 视图。

方法名沿用 `action_view_task_activities`：ControlPanel 以 `parent_res_model` 为 resModel、
`active_id` 为 resId 调用 python_method，`self` 就是当前项目。

## 计算字段

`task_activity_count` 非存储：活动随时间随时增删，缓存失效逻辑没有收益；
项目表单读取时查一次即可。

## 权限

- `self.task_ids` 以当前用户身份读取，受 `project.task` 记录规则约束，
  看不到的任务不会把活动带出来。
- `mail.activity` 的可见性受其自身记录规则约束（用户只看到分配给自己的或
  可访问记录上的活动），无需新增 ACL 或规则。

## 只读

action context 设 `create/edit/delete = False`。汇总视图只用于浏览和打开活动，
活动的生命周期仍归属任务，避免在这里创建与任务脱钩的活动。

## 被否决的方案

- **任务列表加活动数量列**：只能看到计数，看不到活动本身，也无法按项目汇总。
- **改现有任务活动视图**：活动面板是单条任务维度的，无法跨任务按项目汇总。
