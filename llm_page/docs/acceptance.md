# LLM Page — 验收标准

## AC-1 工具注册与创建

全部 `llm_page_*` 工具被 `@llm_tool` 扫描注册为 `llm.tool` 行（executor
`model_method`，source `code`）。`llm_page_create` 消费一个可读且未绑定的
attachment，创建 draft 页、写 source 审计字段并把 attachment 绑定到页面；
`submit=True` 直接 pending；返回 page_id / slug / url / state。 —
`test_all_tools_registered`、`test_create_from_upload`、
`test_rejects_already_used_attachment`

## AC-2 内容形态规范化

- 完整文档（含 `<html>/<head>/<body>`）提取 `<body>` 内层
- 纯正文片段原样保留
- 非 UTF-8 / 空内容拒绝 — `test_body_extraction`、`test_invalid_content_rejected`

## AC-3 审核状态机

- `submit`：draft/rejected → pending
- `approve`：pending → published（写 `date_publish`），非 reviewer 拒绝
- `reject`：pending → rejected（写 `reject_reason`），非 reviewer 拒绝
- `unpublish`：published → draft，非 reviewer 拒绝 —
  `test_workflow_transitions`、`test_reviewer_only_guards`

## AC-4 授权访问（HttpCase）

- 已发布 + group 成员 → 200
- 已发布 + 登录但非成员 → 403
- 已发布 + 匿名 → 跳登录
- 未发布 + 非 reviewer → 404
- 未发布 + reviewer → 200（预览） — `test_controller_authorization`

## AC-5 原始渲染（支持 JS）

`html` 含 `<script>` / `<style>` 时原样出现在渲染结果，不被 sanitize 剥离。 —
`test_raw_html_preserved`

## AC-6 上传来源审计

页面记录 `source_attachment_id` / `source_sha256` / `source_size_bytes` 与上传物
一致；来源 attachment 绑定到页面（`res_model="llm.page"`，`res_id=page.id`）。 —
`test_source_audit`

## 运行方式

```bash
docker exec odoo odoo -c /etc/odoo/odoo.conf -d <db> \
  -i llm_page --test-enable --test-tags /llm_page \
  --stop-after-init --workers=0 --no-http
```

直接创建 `ir.attachment` 作为上传物；无网络、无 API key、无 storage backend。
