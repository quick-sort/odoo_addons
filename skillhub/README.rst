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

安装
====

- 依赖：``storage_backend_mcp``、``llm``（不依赖 ``llm_mcp_server``——工具进
  ``llm.tool`` 后 MCP 服务端自动暴露）。
- 无新增 Python 依赖。

配置
====

- 先在 Storage Backend 上打开 MCP 读写开关（见 ``storage_backend_mcp``）。

详细设计见 ``docs/``。
