# SkillHub — 系统设计

## 数据模型

`skillhub.skill`：一条 skill 包记录 = 元数据 + 指向压缩包 `ir.attachment` 的指针。

- `code`（唯一 slug，稳定身份）、`title`、`description`（搜索）、`version`（展示标签）
- `state`（active/archived）
- `create_uid`（owner，沿用按用户隔离）
- `shared_user_ids`（分享给谁）、`is_public`（全局公开）
- `category_id`（分类，可空；`ondelete="set null"`，删分类不删 skill）
- `depends_on_ids`（依赖哪些 skill，单向）+ `required_by_ids`（反向：谁依赖我）。两张
  字段共享关系表 `skillhub_skill_dependency`（`skill_id` → `dependency_id`），反向字段
  用交换列名实现（`res.groups` 的 `implied_ids`/`trans_implied_ids` 同款），无需 computed。
- `attachment_id`（压缩包，`ir.attachment`，`ondelete="restrict"`）
- `size`、`sha256`（完整性）

压缩包本身是 `ir.attachment`，记录只存指针。

## 文件生命周期

### 上传 + 发布

1. 客户端调用 `attachment_stage_upload(filename)`，拿到 `attachment_id` 和上传 URL。
2. `curl -T` 上传 zip 字节。
3. 调用 `attachment_commit_upload(attachment_id)` 完成校验。
4. `skill_publish(attachment_id, code, title, description, version, ...)`：
   - attachment 必须对调用者可读（`check_access("read")`）；
   - attachment 必须尚未绑定任何业务记录（`res_model`/`res_id` 为空）；
   - 文件不能为空；
   - 在 `savepoint` 内 upsert `skillhub.skill`（写 `attachment_id/size/sha256`），
     再把 attachment 绑定到该 skill（`res_model="skillhub.skill", res_id=skill.id`），
     最后删除被替换的旧 attachment。
   - 任一步失败时 savepoint 回滚：旧 skill 与旧 attachment 保持原样；新 attachment
     仍未绑定，可重试。

绑定即消费：同一个 attachment 不能再次用于另一个 skill，否则第二条记录会改变第一条
记录的权限来源。

### 下载

`skill_download(skill_id)` 先按技能级 record rules 判断调用者能否读该 skill，再委托
`llm.mcp.file.tool.attachment_get_download_url(attachment_id)`。该工具会再次以调用者身份
执行 `ir.attachment.check_access("read")`：attachment 已绑定到 skill，因此权限自然跟随
skill 的 owner/shared/public 规则，不需要 sudo，也不依赖存储后端开关。

### 替换与归档

- 同 `code` 再发布：新 attachment 绑定到同一 skill，旧 attachment 删除。
- 归档（`state="archived"`）保留 attachment；没有删除入口。
- 旧版本（未迁移数据）可能没有 `attachment_id`，`skill_download` 会明确要求重新发布。

## 授权模型

三层访问，record rules 落地：

| 角色 | 权限 |
|---|---|
| owner（create_uid） | 读 / 写 / 删 / 分享 / 下载 |
| shared_user_ids | 读 + 下载 |
| is_public | 所有内部用户读 + 下载 |
| 管理员（`base.group_system`） | 读 / 写全部（`create` / `unlink` 仍由模型 ACL 决定） |

- 读 record rule：`owner OR shared OR public`。
- 写 / 删 / 分享：仅 owner。
- 管理员放行：一条 `base.group_system` 的组规则（`[(1, '=', 1)]`）。Odoo 对同一
  操作的组规则取 **OR**，所以普通用户的可见范围不变，管理员能看/改全部。

文件权限不再单独设计：`ir.attachment` 的绑定记录规则与 skill 完全一致。工具向
`base.group_user` 开放，实际能操作哪条记录仍由 record rules 决定。

## 工具面（`@llm_tool`，经 `llm_mcp_server` 暴露）

- `skill_publish(attachment_id, code, title, description, version, category_id?, depends_on_ids?)`
  → `{skill_id, attachment_id}`（`category_id` 省略时保留已有分类；`depends_on_ids`
  省略时保留已有依赖，显式列表——含空列表——整体替换）
- `skill_download(skill_id)` → `{download, curl}`
- `skill_share(skill_id, user_ids)` / `skill_unshare(skill_id, user_ids)`（仅 owner）
- `skill_archive(skill_id)`（仅 owner）

纯读/搜索不设独立 tool，走通用 `odoo_record_retriever`（搜索约定记在
`llm.tool.guide`，code=`skillhub`）。

## 后端 UI

定位：**浏览 + 元数据编辑**。发布/下载生命周期仍归 MCP 工具，UI 不参与文件读写。

- 菜单：根菜单 `menu_skillhub_root` + 子菜单 `menu_skillhub_skill`（Skills）+
  `menu_skillhub_category`（Categories，管理员维护分类）。
- 列表：`create="false" delete="false"`。记录由 `skill_publish` 产生。
- 表单可编辑：title / description / version / is_public / shared_user_ids /
  category_id / depends_on_ids / state（仅 owner，record rule 兜底）。
- 表单只读：code / attachment_id / size / sha256 / create_uid / required_by_ids。
- 搜索：按 code/title/description 搜；过滤 Archived / My Skills / Shared With Me /
  Public；按 state/owner 分组；search panel 按 `category_id` 多选筛选。

## 关键取舍

### 为什么用 `ir.attachment` 而不是自存 `(backend, path)`
`ir.attachment` 是 Odoo 原生文件身份：权限随绑定记录走，下载走 `/web/content`，
字节存储位置（DB/filestore/外部 storage）对业务透明。消费方只持有 attachment id，
不再需要知道 backend/path。

### 为什么绑定即消费
绑定把文件挂到唯一业务记录上，既让权限有明确宿主，也阻止同一个文件被重复挂到多条
记录。若允许复用，第二条记录的 ACL 会改变第一条记录的可见范围。

### 为什么单版本覆盖
目标是用最新的 skill 包；历史版本是另一套问题（registry 语义），先单版本 + `version`
字段。

## 被否决的方案

| 方案 | 否决理由 |
|---|---|
| zip 内容解析进 Odoo（SKILL.md → 字段） | 格式是客户端的事，解析会跟客户端耦合、随格式漂移。 |
| tags（自由多标签）分类搜索 | 用户定：单一 `category_id` 分类够用，不做自由标签；搜索仍只按名字/描述。 |
| 版本历史 | 先单版本覆盖够用，历史留作将来。 |
| 自存 `(backend, path)` / presign 下载 | storage MCP 已移除；attachment 原生权限与 URL 足够，且不暴露存储拓扑。 |
| 复用同一个 attachment 发布多个 skill | 一条 attachment 只能绑定一条业务记录，复用会破坏先前记录的权限来源。 |
| base64 进 tool arguments | 字节流不过 MCP 通道。 |
| 依赖环（多跳闭环）检测 | 单跳自依赖约束已够；闭环/传递闭包是另一套图算法问题，先不做。 |
