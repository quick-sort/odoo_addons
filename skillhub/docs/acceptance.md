# SkillHub — 验收标准

> 这是 QC 的唯一依据。每个功能点（AC-x）必须有一个对应的测试；测试全绿才算通过。

## AC-1 数据模型

`skillhub.skill` 含 `code`(unique)/`title`/`description`/`version`/`is_public`/
`shared_user_ids`/`category_id`/`attachment_id`/`size`/`sha256`。 — `test_model_fields`

## AC-2 发布新建

`skill_publish(attachment_id, code, ...)` 消费一个可读且未绑定的 attachment，把它绑定到
新建 skill，并记录 size/sha256。 — `test_publish_creates_skill`

## AC-3 发布更新

同 `code` 再发布 → 新 attachment 绑定到同一记录、元数据更新、旧 attachment 删除。 —
`test_publish_updates_existing`

## AC-4 下载

`skill_download(skill_id)` 返回 `/web/content/ir.attachment/...` 的短期签名 URL。 —
`test_download_returns_url`

## AC-5 搜索

读/搜索不设独立 tool；由 `odoo_record_retriever` 完成，active-only + code/title/description
ilike 的约定记在 `llm.tool.guide`（code=`skillhub`）正文。 — `test_guide_contributed`

## AC-6 授权读

owner / shared / public 可见；其他用户不可见（record rule）。 — `test_read_isolation`

## AC-7 分享

仅 owner 能 `skill_share` / `skill_unshare`。 — `test_share_owner_only`

## AC-8 下载鉴权

非 owner/shared/public 调 `skill_download` 被拒；owner / shared / public 都要能拿到
下载地址 —— **包括不带管理员组的普通用户**。附件权限由绑定记录继承，不再有存储后端
开关。 —
`test_download_requires_access` / `test_plain_user_can_download_shared_skill` /
`test_plain_user_can_download_public_skill` / `test_plain_user_cannot_download_unshared_skill`

## AC-9 后端 UI

应用入口/菜单/action/视图（list/form/search）可解析；列表禁止新建与删除；表单中
技术字段（code/attachment_id/size/sha256/owner）只读，元数据字段
（title/description/version/is_public/shared_user_ids/category_id/state）可编辑。 —
`test_ui_views_resolve` / `test_list_blocks_create_delete` /
`test_form_readonly_matrix` / `test_menu_structure_and_icon`

## AC-10 分类

`skillhub.category` 模型（`name` 唯一）；skill 挂 `category_id`；`skill_publish`
接受可选 `category_id`（省略时保留已有分类）；skill 列表 search panel 按 `category_id`
多选筛选。 —
`test_category_assigned` / `test_publish_keeps_category_when_omitted` /
`test_search_panel_category`

## AC-11 依赖

`skillhub.skill` 含 `depends_on_ids`（依赖哪些 skill）+ `required_by_ids`（反向）；
`skill_publish` 接受可选 `depends_on_ids`（省略时保留已有依赖）；禁止自依赖。 —
`test_dependency_assigned_and_returned` / `test_publish_sets_dependencies` /
`test_publish_keeps_dependencies_when_omitted` / `test_self_dependency_rejected`

## AC-12 失败的发布不破坏已发布的包

发布在 `savepoint` 内完成：写 skill、绑定新 attachment、删除旧 attachment。任何一步
失败都会回滚，skill 仍指向旧 attachment；新 attachment 保持未绑定。 —
`test_failed_publish_keeps_previous_package`

## AC-13 attachment 消费契约

`skill_publish` 只接受调用者可读、未绑定、非空的 attachment；已绑定文件、他人未共享的
未绑定文件、空文件均被拒绝。走 `attachment_stage_upload` / `attachment_commit_upload`
的端到端流程可用。 —
`test_publish_rejects_already_bound_attachment` / `test_publish_rejects_foreign_attachment` /
`test_publish_rejects_empty_attachment` / `test_publish_via_staged_upload`

## AC-15 管理员可见全部

管理员（`base.group_system`）不受 owner / shared / public 限制，能看到、编辑并下载
其他人的 skill；普通用户（不带管理员组）仍只看到 owner / shared / public 的记录。 —
`test_admin_sees_and_can_edit_any_skill` / `test_read_isolation`
