# SkillHub — 系统设计

## 数据模型

`skillhub.skill`：一条 skill 包记录 = 元数据 + 指向 storage 里压缩包的指针。

- `code`（唯一 slug，稳定身份）、`title`、`description`（搜索）、`version`（展示标签）
- `state`（active/archived）
- `create_uid`（owner，沿用按用户隔离）
- `shared_user_ids`（分享给谁）、`is_public`（全局公开）
- `backend_id` + `storage_path`（压缩包在 storage 里的位置，如 `skillhub/<code>.zip`）
- `size`、`sha256`（完整性）

压缩包本身存 `storage.backend`，Odoo 只存指针，不存 blob。

## 与 storage_backend_mcp 的关系

- **上传**：`skill_publish(file_id, code, title, description, version)` 调
  `storage.upload.consume()` 读回上传的压缩包，再 `backend.open(storage_path, "wb")`
  落到稳定路径，计算 sha256/size，upsert `skillhub.skill`（按 code：不存在则建、存在则覆盖）。
- **下载**：`skill_download(skill_id)` 先做技能级鉴权，再 `backend.presign_download(storage_path)`
  拿临时 URL（presign 直连 / relay token 兜底），返回 `{download, curl}`。

复用而不重复 storage_backend_mcp 的「presign + relay」下载 spec 逻辑。

## 授权模型

三层访问，record rules 落地：

| 角色 | 权限 |
|---|---|
| owner（create_uid） | 读 / 写 / 删 / 分享 / 下载 |
| shared_user_ids | 读 + 下载 |
| is_public | 所有人读 + 下载 |

- 读 record rule：`owner OR shared OR public`。
- 写 / 删 / 分享：仅 owner。

鉴权双层：**技能级**（skillhub 的 record rules + `skill_download`/`skill_share` 显式校验）
管「谁能拿这个 skill」；**后端级**（storage backend 的 `mcp_read_enabled`）管「谁能读这个 backend」。

## 工具面（`@llm_tool`，经现有 `llm_mcp_server` 暴露）

- `skill_publish(file_id, code, title, description, version)` → `{skill_id}`
- `skill_search(query?)` → `[{skill_id, code, title, description, version}]`（只返回 caller 可见）
- `skill_get(skill_id)` → 元数据
- `skill_download(skill_id)` → `{download, curl}`
- `skill_share(skill_id, user_ids)` / `skill_unshare(skill_id, user_ids)`（仅 owner）
- `skill_archive(skill_id)`（仅 owner）

## 关键取舍

### 为什么存 `storage_path` 指针而不是 zip 进 DB
blob 进 DB 会膨胀、且失去 storage 的 presign 下载（bypass Odoo）与上传治理。指针 + storage 才是正解。

### 为什么消费方收 `file_id` 而非 `(backend, path)`
见 storage_backend_mcp design：引用范围限定在「该用户经 audited 上传、且未消费」的集合。

### 为什么单版本覆盖
目标是用最新的 skill 包；历史版本是另一套问题（registry 语义），先单版本 + `version` 字段。

## 被否决的方案

| 方案 | 否决理由 |
|---|---|
| zip 内容解析进 Odoo（SKILL.md → 字段） | 格式是客户端的事，解析会跟客户端耦合、随格式漂移。 |
| tags 分类搜索 | 用户定：只按名字/描述搜索，保持简单。 |
| 版本历史 | 先单版本覆盖够用，历史留作将来。 |
| base64 进 tool arguments | 字节流不过 MCP 通道，见 storage_backend_mcp。 |
