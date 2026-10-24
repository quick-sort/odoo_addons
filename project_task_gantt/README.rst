========================
 Project Task Gantt
========================

为 ``project.task`` 提供 Gantt 视图，按时间轴查看项目任务的起止时间、父子层级
与负责人。

用法
====

- 依赖 ``project`` 与 ``web_gantt``；无额外 Python 依赖。
- 安装后，项目任务列表和「全部任务」可在视图切换器中打开 Gantt。
- 任务表单新增 Start Date / Duration；Gantt 的结束时间就是任务的截止日期
  （``date_deadline``），不再单独存 End Date。
- 左侧列表按 ``parent_id`` 展示层级，有子任务的行可折叠；任务名右侧显示负责人。
- 可在顶部按项目、负责人、阶段、优先级分组。
- 图中用竖向标记线展示相关项目的 milestone 日期：已达成为灰色、未达成为主色；
  标签常显（密集时错行/省略），悬停可看名称、日期与状态。

注意
====

- 只有设置了 Start Date 的任务会出现在图中；未设置 Deadline 时按 1 天显示。
- 旧字段名 ``task_end_date`` 保留为**非存储**兼容别名（读写/搜索等价于
  ``date_deadline``），供已有列表视图继续引用；新代码请直接用 Deadline。
- 行顺序按 ``sequence``，拖动任务只改时间，不改变行顺序。

详细设计见 ``docs/design.md``，验收标准见 ``docs/acceptance.md``。
