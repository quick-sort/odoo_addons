========================
 Project Task Gantt
========================

为 ``project.task`` 提供 Gantt 视图，按时间轴查看项目任务的起止时间、父子层级
与负责人。

用法
====

- 依赖 ``project`` 与 ``web_gantt``；无额外 Python 依赖。
- 安装后，项目任务列表和「全部任务」可在视图切换器中打开 Gantt。
- 任务表单新增 Start Date / End Date / Duration 字段；起止时间与任务的截止日期
  （``date_deadline``）保持同步。
- 左侧列表按 ``parent_id`` 展示层级，有子任务的行可折叠；任务名右侧显示负责人。
- 可在顶部按项目、负责人、阶段、优先级分组。

注意
====

- 只有设置了 Start Date 的任务会出现在图中；未设置 End Date 时按 1 天显示。
- 行顺序按 ``sequence``，拖动任务只改时间，不改变行顺序。

详细设计见 ``docs/design.md``，验收标准见 ``docs/acceptance.md``。
