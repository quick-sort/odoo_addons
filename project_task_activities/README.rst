==========================
 Project Task Activities
==========================

把项目下所有任务的待办活动（activity）汇总到一个入口，方便按项目统一查看。

用法
====

- 依赖 ``project``；无新增 Python 依赖。
- 打开项目表单，点 smart button「Activities」即可看到该项目下所有任务的活动列表。
- 从项目进入任务视图后，也可以在右上角「Top Menu」里点「Activities」打开同一列表。
- 列表为只读；新增/完成/取消活动请回到对应任务。

注意
====

- 活动就是普通的 ``mail.activity``（``res_model = 'project.task'``）。
- 只统计任务活动，项目本身（``project.project``）的活动不计入。

详细设计见 ``docs/design.md``，验收标准见 ``docs/acceptance.md``。
