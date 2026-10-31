==========
 SkillHub
==========

给第三方 MCP 客户端（Claude Code、OpenClaw 等）用的 skill 压缩包仓库：发布、搜索、
分享、下载。

工作方式
========

- 贡献一组 ``skill_*`` LLM/MCP 工具（发布/下载/分享/归档），经 ``@llm_tool``
  自动注册，MCP 客户端与内部 agent 双端可用；读/搜索不设独立 tool，走通用
  ``odoo_record_retriever``（约定见 ``llm.tool.guide``，code=`skillhub`）。
- 压缩包以 ``ir.attachment`` 存储，元数据（code/title/description/version/
  category/依赖）存 ``skillhub.skill``；不解析压缩包内容。
- 上传使用 ``llm_mcp_server`` 的 attachment 文件机制：
  ``attachment_stage_upload`` → 客户端 curl 传包 → ``attachment_commit_upload`` →
  ``skill_publish(attachment_id, ...)``。attachment 必须对调用者可读且尚未绑定；
  publish 把它绑定到 skill，即完成一次性消费。
- 下载返回 ``/web/content`` 短期签名 URL；权限跟随 skill 的 record rules
  （owner / shared / public），不需要 storage backend 的额外开关。

界面
====

- SkillHub 以独立应用出现在 Odoo 后台，Skills 菜单列出全部可见（owner/分享给
  自己/公开）的 skill，可搜索、按状态/owner 筛选分组；列表左侧 search panel
  按分类（category）多选筛选。Categories 菜单由管理员维护分类。
- owner 可在表单里编辑元数据（title/description/version/category/is_public/分享
  用户/依赖的 skill/归档状态）；技术字段（code/attachment/大小/校验和/被哪些 skill
  依赖）只读。
- 界面不提供新建与删除：记录由 ``skill_publish`` 产生，归档才是生命周期出口。

安装
====

- 依赖：``llm_mcp_server``、``llm``。
- 无新增 Python 依赖。

详细设计见 ``docs/``。
