# SkillHub — 验收标准

> 这是 QC 的唯一依据。每个功能点（AC-x）必须有一个对应的测试；测试全绿才算通过。

## AC-1 数据模型

`skillhub.skill` 含 `code`(unique)/`title`/`description`/`version`/`is_public`/
`shared_user_ids`/`backend_id`/`storage_path`/`size`/`sha256`。 — `test_model_fields`

## AC-2 发布新建

`skill_publish(file_id, code, ...)` 消费上传物、落到 storage、建记录（记录 size/sha256）。 — `test_publish_creates_skill`

## AC-3 发布更新

同 `code` 再发布 → 覆盖 blob、更新元数据、仍是同一条记录。 — `test_publish_updates_existing`

## AC-4 下载

`skill_download(skill_id)` 返回 presign URL（无原生签名后端返回 relay token）。 — `test_download_returns_url`

## AC-5 搜索

按 `code`/`title`/`description` 模糊匹配。 — `test_search_by_name_and_description`

## AC-6 授权读

owner / shared / public 可见；其他用户不可见（record rule）。 — `test_read_isolation`

## AC-7 分享

仅 owner 能 `skill_share` / `skill_unshare`。 — `test_share_owner_only`

## AC-8 下载鉴权

非 owner/shared/public 调 `skill_download` 被拒。 — `test_download_requires_access`

## AC-9 后端 UI

应用入口/菜单/action/视图（list/form/search）可解析；列表禁止新建与删除；表单中
技术字段（code/backend_id/storage_path/size/sha256/owner）只读，元数据字段
（title/description/version/is_public/shared_user_ids/state）可编辑。 —
`test_ui_views_resolve` / `test_list_blocks_create_delete` /
`test_form_readonly_matrix` / `test_menu_structure_and_icon`
