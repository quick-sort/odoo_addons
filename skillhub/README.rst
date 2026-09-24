==========
 SkillHub
==========

给第三方 MCP 客户端（Claude Code、OpenClaw 等）用的 skill 压缩包仓库：发布、搜索、
分享、下载。

工作方式
========

- 贡献一组 ``skill_*`` LLM/MCP 工具（发布/搜索/查看/下载/分享/归档），经
  ``@llm_tool`` 自动注册，MCP 客户端与内部 agent 双端可用。
- 压缩包以 blob 存 ``storage.backend``，元数据（code/title/description/version）存
  ``skillhub.skill``；不解析压缩包内容。
- 上传复用 ``storage_backend_mcp`` 的 file_id：``storage_stage_upload`` → 客户端 curl
  传包 → ``skill_publish(file_id, ...)`` 消费并落库到稳定路径。
- 下载返回 presign URL（bypass Odoo），按 owner / shared / public 三层授权。

界面
====

- SkillHub 以独立应用出现在 Odoo 后台，Skills 菜单列出全部可见（owner/分享给
  自己/公开）的 skill，可搜索、按状态/后端/owner 筛选分组。
- owner 可在表单里编辑元数据（title/description/version/is_public/分享用户/归档
  状态）；技术字段（code/backend/路径/校验和）只读。
- 界面不提供新建与删除：记录由 ``skill_publish`` 产生，删除会留下孤儿 blob，归档
  才是生命周期出口。

安装
====

- 依赖：``storage_backend_mcp``、``llm``（不依赖 ``llm_mcp_server``——工具进
  ``llm.tool`` 后 MCP 服务端自动暴露）。
- 无新增 Python 依赖。

配置
====

- 先在 Storage Backend 上打开 MCP 读写开关（见 ``storage_backend_mcp``）。

详细设计见 ``docs/``。
