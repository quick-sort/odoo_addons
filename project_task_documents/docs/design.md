# Project Task Documents — 设计

## 数据来源

不新增模型：文档就是 `ir.attachment`，按 `res_model = 'project.task'` 且
`res_id in 项目任务 ids` 查询。

这个查询同时覆盖 chatter 附件：`message_post` 会把附件写回记录
（`mail/models/mail_thread.py` 的 `_process_attachments_for_post`），因此消息附件、
直接上传和「Document」活动上传的附件都带任务级 `res_model/res_id`，一遍查询即可。

## 入口

project 表单 `button_box` 加 `oe_stat_button`（`widget="statinfo"`），
`type="object"` 调 `project.project.action_view_task_attachments()`。

方法返回 `ir.actions.act_window`，`res_model = ir.attachment`，
`domain` 由 `_get_task_attachment_domain()` 统一生成，`task_attachment_count`
用同一个 domain 的 `search_count`，避免两处口径不一致。

## 计算字段

`task_attachment_count` 非存储：附件随 chatter 随时变化，缓存失效逻辑没有收益；
项目表单读取时查一次即可。

## 任务视图入口（embedded action）

从项目进入任务视图后，Odoo 19 的 ControlPanel 通过 embedded actions 提供「Top Menu」
入口。新增一条 `ir.embedded.actions`（`views/embedded_actions.xml`）：

- `parent_action_id = project.act_project_project_2_project_task_all`（项目的任务 action）
- `parent_res_model = project.project`（可见性判断所针对的 active 记录模型）
- `python_method = action_view_task_attachments`（复用 smart button 的方法）
- `groups_ids = project.group_project_user`

不用 `action_id` 指向静态 act_window：目标 domain 依赖当前项目的任务 ids，状态 window
的静态 domain 表达不了（`ir.attachment` 上没有 project_id 可 join），必须动态返回。

可见性由 `ir.embedded.actions.is_visible` 计算，要求 `context.active_id` 是当前用户
可访问的项目，否则按钮不出现；所以只在「从项目进入任务」时显示，从全局 All Tasks 菜单
进入时不显示。另外 embedded actions 不渲染在 form 视图，因此入口只出现在任务的
list/kanban/graph/pivot/activity 视图。

方法名沿用 `action_view_task_attachments`：ControlPanel 以 `parent_res_model` 为 resModel、
`active_id` 为 resId 调用 python_method，`self` 就是当前项目。

## 权限

- `self.task_ids` 以当前用户身份读取，受 `project.task` 记录规则约束，
  看不到的任务不会把附件带出来。
- `ir.attachment` 对内部用户为可读（`base` 的 ACL），无需新增 ACL 或规则。

## 只读列表

action context 设 `create/edit/delete = False`。汇总页只用于浏览和下载，附件的
生命周期仍归属任务，避免在这里创建无归属附件或误删。

## 被否决的方案

- **企业版 Documents 文件夹**：依赖 enterprise `documents`，社区环境不可用，
  且只能覆盖配置了 Folder 的活动类型，不能覆盖已有 chatter 附件。
- **任务列表加附件数量列**：只能看到计数，看不到文件本身，也无法按项目汇总。
