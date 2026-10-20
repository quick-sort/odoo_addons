========================
 Project Task Documents
========================

把项目下所有任务的附件（包括 chatter 附件和通过「Document」活动上传的文件）
汇总到一个入口，方便按项目统一查看和下载。

用法
====

- 依赖 ``project``；无新增 Python 依赖。
- 打开项目表单，点 smart button「Documents」即可看到该项目下所有任务的附件列表。
- 列表为只读；新增/编辑/删除附件请回到对应任务。

注意
====

- 文档就是普通的 ``ir.attachment``（``res_model = 'project.task'``），
  社区版没有独立的文档对象。
- 只统计任务附件，项目本身（``project.project``）的附件不计入。

详细设计见 ``docs/design.md``，验收标准见 ``docs/acceptance.md``。
