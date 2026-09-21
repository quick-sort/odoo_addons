# SkillHub — 业务需求

## 要解决的问题

让第三方 MCP 客户端（Claude Code、OpenClaw 等）能把「技能（skill）」以压缩包形式
发布到一个集中仓库，按名字/描述搜索，按用户授权分享，并下载到本地。

本模块只管理 skill 压缩包（blob）+ 元数据（名称/描述/版本）+ 授权，**不解析压缩包
内容**（那是客户端的事，Odoo 只当 opaque blob 存）。

## 范围

**做**：

- 发布：上传 skill 压缩包（经 storage_backend_mcp 的 `file_id` 消费），落到
  `storage.backend` 的稳定路径
- 更新：同 `code` 再发布即覆盖
- 搜索：按 `code` / `title` / `description` 模糊匹配
- 下载：返回临时 URL（presign，bypass Odoo）
- 授权：owner（create_uid）/ `shared_user_ids`（分享给指定人）/ `is_public`（全局公开）
- 元数据：code / title / description / version / size / sha256

**不做**：

- 不解析/校验压缩包内容（SKILL.md 结构等），当 blob 存
- 不做版本历史（单版本覆盖，`version` 字段只作展示标签）
- 不做标签/分类搜索（只按名字/描述）
- 不集成进本仓库 `llm` 模块的 agent 运行时（本模块面向第三方 MCP 客户端）

## 非功能要求

1. **字节流不过 MCP 通道**：上传/下载复用 storage_backend_mcp 的 URL broker。
2. **按用户隔离**：owner 用 `create_uid`，record rules 管读；写/删/分享仅 owner。
3. **可审计**：发布/下载留 owner 与时间。
4. **离线可测**：mock storage backend，无网络、无 API key。
