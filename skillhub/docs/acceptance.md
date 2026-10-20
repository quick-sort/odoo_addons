# SkillHub — 验收标准

> 这是 QC 的唯一依据。每个功能点（AC-x）必须有一个对应的测试；测试全绿才算通过。

## AC-1 数据模型

`skillhub.skill` 含 `code`(unique)/`title`/`description`/`version`/`is_public`/
`shared_user_ids`/`category_id`/`backend_id`/`storage_path`/`size`/`sha256`。 — `test_model_fields`

## AC-2 发布新建

`skill_publish(file_id, code, ...)` 消费上传物、落到 storage、建记录（记录 size/sha256）。 — `test_publish_creates_skill`

## AC-3 发布更新

同 `code` 再发布 → 覆盖 blob、更新元数据、仍是同一条记录。 — `test_publish_updates_existing`

## AC-4 下载

`skill_download(skill_id)` 返回 presign URL（无原生签名后端返回 relay token）。 — `test_download_returns_url`

## AC-5 搜索

读/搜索不设独立 tool；由 `odoo_record_retriever` 完成，active-only + code/title/description
ilike 的约定记在 `llm.tool.guide`（code=`skillhub`）正文。 — `test_guide_contributed`

## AC-6 授权读

owner / shared / public 可见；其他用户不可见（record rule）。 — `test_read_isolation`

## AC-7 分享

仅 owner 能 `skill_share` / `skill_unshare`。 — `test_share_owner_only`

## AC-8 下载鉴权

非 owner/shared/public 调 `skill_download` 被拒；反过来，owner / shared / public 都要能拿到
下载地址 —— **包括不带管理员组的普通用户**。分享给谁，谁就得拿得到包，不能只让他看见列表。 —
`test_download_requires_access` / `test_plain_user_can_download_shared_skill` /
`test_plain_user_can_download_public_skill` / `test_plain_user_cannot_download_unshared_skill`

## AC-9 后端 UI

应用入口/菜单/action/视图（list/form/search）可解析；列表禁止新建与删除；表单中
技术字段（code/backend_id/storage_path/size/sha256/owner）只读，元数据字段
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

`skill_publish` **先写库、后落位**：压缩包先流到暂存路径，记录写成功后才改名到稳定
路径。因此在写库阶段失败的发布（例如触发自依赖约束）**不得覆盖**已发布的压缩包 ——
记录及其 `sha256` 仍描述磁盘上实际存在的那个文件。 —
`test_failed_publish_keeps_the_previous_blob`

## AC-13 下载只认自己那条包

`skill_download` 的路径**由 `code` 推导**（`skillhub/<code>.zip`），不信任记录里存的
`storage_path`；两者不一致时拒绝下载。否则一条伪造的记录可以把「分享 skill」变成
「读取存储后端任意文件」。 — `test_download_refuses_a_record_pointing_at_another_skills_package`

## AC-14 记录只能由发布产生

`skillhub.skill` 的模型级 ACL **不授予 `create` / `unlink`**：记录只能经 `skill_publish`
产生，UI 与 ORM 都不允许手工新建或删除。owner 仍可在表单里修改元数据。 —
`test_skill_records_cannot_be_created_by_hand`

