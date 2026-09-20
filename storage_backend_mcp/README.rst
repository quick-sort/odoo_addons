===================================
 Storage Backend MCP
===================================

让 agent（MCP 客户端 / Odoo 内部 agent）向 ``storage.backend`` 上传、下载、
浏览文件，并以 ``file_id`` 为货币把上传物交给下游工具（如 skillhub）消费。

工作方式
========

- 贡献一组 ``storage_*`` LLM/MCP 工具（浏览、读、直写 URL、暂存上传、删除），
  经 ``@llm_tool`` 自动注册，MCP 客户端与内部 agent 双端可用。
- 上传/下载以**临时 URL** 为载体，字节流不过 MCP 通道：
  有原生签名能力的后端直连对象存储（装 bridge，如
  ``storage_backend_s3_mcp``），其余走 Odoo 中转 controller
  （一次性 capability token，短 TTL + 尺寸上限）。
- 暂存上传协议：``storage_stage_upload`` → agent 用 curl 传 →
  ``storage_commit_upload``（校验 sha256/size）→ 下游工具以
  ``storage.upload.consume()`` 消费。未消费的暂存物自动过期清理。
- 每后端 ``mcp_read_enabled`` / ``mcp_write_enabled`` 治理开关（默认关）；
  权限沿用 ``storage_backend`` 的 ``group_system`` ACL。

安装
====

- 依赖：``storage_backend``、``llm``（本 addon 不依赖 ``llm_mcp_server``——
  工具注册进 ``llm.tool`` 后 MCP 服务端自动暴露）。
- 无新增 Python 依赖。

配置
====

- 在 Storage Backend 表单上打开 MCP 读/写开关。
- ``storage_backend_mcp.max_relay_size_mb``（默认 2048）：中转路径上传硬上限。

扩展
====

- 新后端要原生签名 URL：新 bridge addon，组件继承对应 adapter，
  覆盖 ``presign_upload/presign_download``（参考 ``storage_backend_s3_mcp``）。
- 下游工具消费上传物：``storage.upload.consume()`` 上下文管理器。

详细设计见 ``docs/``。
