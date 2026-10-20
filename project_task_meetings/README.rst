========================
 Project Task Meetings
========================

把项目下所有任务关联的会议（``calendar.event``）汇总到一个入口，方便按项目
统一查看。

用法
====

- 依赖 ``project``、``calendar``；无新增 Python 依赖。
- 打开项目表单，点 smart button「Meetings」即可看到该项目下所有任务关联的
  会议日历。
- 从项目进入任务视图，Top Menu 中也有「Meetings」入口，打开同一日历。
- 视图为只读；新建/编辑会议请回到对应任务。

注意
====

- 会议就是普通的 ``calendar.event``（``res_model = 'project.task'``）。
- 只统计任务关联的会议，项目本身（``project.project``）关联的会议不计入。

详细设计见 ``docs/design.md``，验收标准见 ``docs/acceptance.md``。
