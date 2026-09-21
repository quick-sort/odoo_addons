# LLM Page — 系统设计

## 总体形态

agent 生成 HTML → storage MCP 暂存上传（stage/commit 得 `file_id`）→ 本模块工具
`llm_page_create(file_id)` 消费上传、登记为草稿 → 审核员后台预览/通过 → 发布页
以 website 主题渲染，仅授权组可访问。

```
agent ──storage_stage_upload/commit──▶ storage.upload (staged)
        ──llm_page_create(file_id)─▶ llm.page (draft)
                                            │  审核（后台）
                                            ▼
                                    llm.page (published)
                                            │  GET /static/<slug>
                                            ▼
                              website.layout 包裹 + group_id 鉴权渲染
```

与 `storage_backend_mcp` 分层同构：本模块是 storage MCP 的**下游消费方**，通过
`storage.upload.consume()` 单次读取上传物；不为存储再造一套引用货币。

## 数据模型 `llm.page`

| 字段 | 说明 |
|---|---|
| `name` | 页面标题（浏览器标题/后台显示） |
| `slug` | URL 段，唯一；路由 `/static/<slug>` |
| `html` | 页面正文 HTML，**原始存储**（`fields.Text`，不 sanitize，支持 JS） |
| `group_id` | 访问控制组（Many2one `res.groups`，默认模块 viewer 组），仅该组成员可访问已发布页 |
| `state` | `draft` / `pending` / `published` / `rejected` |
| `website_id` | 归属网站（多站点），默认当前网站 |
| `date_submit` / `date_publish` / `date_reject` | 流程时间戳 |
| `reject_reason` | 驳回原因 |
| `source_backend_id` / `source_sha256` / `source_size_bytes` | 上传来源审计 |

### 内容形态约定

上传物是**正文片段**（body fragment），注入到主题布局的 `<div id="wrap">` 内。
若上传的是完整 HTML 文档（含 `<html>/<head>/<body>`），消费时提取 `<body>`
内层、忽略外层包装；`<head>` 由 `website.layout` 统一管理。外部资源以
`<script src>` / `<link>` 写在正文片段内即可（浏览器在 body 内同样加载执行）。

## 安全模型：为什么可以 raw HTML

根 CLAUDE.md 对「第三方 HTML 上公开页」要求 `fields.Html(sanitize=True)` +
`t-out`。本模块**有意偏离**：需求明确要求默认支持 JS，sanitize 会剥离
`<script>` / `<style>`。

偏离成立的前提，是两条**不可同时缺省的闸门**：

1. **审核闸门**：内容必须经 `group_reviewer` 通过才进入 `published`；只有受信
   审核员能放行脚本。
2. **访问闸门**：发布页仅 `group_id` 成员可访问（默认内部用户组），不是真正
   意义上的公开页；脚本影响面被限定在授权组内。

因此渲染用 `Markup(page.html)` + `t-out`（把信任显式化，而非全局 `t-raw`），
信任边界落在「审核员放行」这一动作上。若某页要面向更宽人群，审核员应换用更窄
的 `group_id` 或人工审查脚本——这是操作责任，不是代码可自动保证的。

## 授权访问（Controller）

路由 `GET /static/<slug>`，`auth='public', website=True`（公开可达但内容鉴权）：

1. 按 slug + 当前网站解析页面；无 → 404。
2. 请求用户是 `group_reviewer` → 视为预览，放行（可看 draft/pending/published/rejected）。
3. 否则 `state != published` → 404（不泄露未发布页存在性）。
4. 已发布：检查 `group_id`——匿名跳登录，登录但非成员 → 403。

`_can_view(user)` 封装上述判定，controller 只调用它；页面解析用 `sudo`，鉴权在
真实用户上判断。

## 审核流程（三级 + 驳回）

```
draft ──提交──▶ pending ──通过──▶ published
  ▲                │                │
  └──重新提交────驳回──▶ rejected    └──下架──▶ draft
```

状态迁移由模型方法承载（`action_submit` / `action_approve` / `action_reject` /
`action_unpublish`）。`approve` / `reject` / `unpublish` 内部校验调用者属
`group_reviewer`（代码层兜底，不依赖视图按钮显隐）。`approve` 写 `date_publish`，
`reject` 写 `reject_reason`。

## MCP 工具（`llm.page.tool`）

| 工具 | 说明 |
|---|---|
| `llm_page_create(file_id, name, slug, submit=False)` | consume 上传物 → 提取正文 → 建草稿（可选直接提交） |
| `llm_page_list()` | 列出页面（id / name / slug / state / url） |
| `llm_page_status(page_id)` | 单页状态 |
| `llm_page_submit(page_id)` | 提交审核（draft/rejected → pending） |

安全决策：**agent 不指定 `group_id`**——创建时落默认 viewer 组，访问组调整是
审核员在后台的操作，避免 agent 借工具把页面指到更宽权限组。

## 权限（ACL / 组）

- `group_viewer`：可访问已发布页（授权访问的默认组）。
- `group_reviewer`：后台全量 CRUD + 审核操作 + 预览；隐含 `group_viewer`。
- ACL：`group_viewer` 读；`group_reviewer` 读写删。
- MCP 工具创建草稿走内部受控路径（工具方法边界内 `sudo`，仅允许构造受限字段
  `name/slug/html/website_id/state ∈ {draft, pending}`），不向普通内部用户开放
  任意写。

## 渲染模板

QWeb 模板继承 `website.layout`，正文注入处：

```xml
<template id="page_template">
  <t t-call="website.layout">
    <div id="wrap">
      <t t-out="html"/>   <!-- html 为 Markup，安全地原样输出 -->
    </div>
  </t>
</template>
```

## 被否决的方案

| 方案 | 否决理由 |
|---|---|
| 用 `website.page`（ir.ui.view/arch）存内容 | arch 是 QWeb XML，任意 HTML（含 JS、非闭合标签）不合法；QWeb 会误读 `t-*`。 |
| `fields.Html(sanitize=True)` 存内容 | 剥离 script/style，违背「默认支持 JS」。 |
| 公开访问 + 仅靠审核把关 | 需求明确「指定用户组」授权，公开页脚本面过大。 |
| agent 直接指定 `group_id` | 越权放大：agent 可把页面指向任意宽权限组。 |
| 内容留在 storage backend、controller 实时读后端 | 审核需稳定可预览的快照；consume 单次读取后对象即删，实时读后端会失去审计闭环。 |

## 明确的扩展点

1. 正文片段内 head 资源（title/meta）→ 将来映射到 `website.seo.metadata` mixin。
2. 多文件 / 资源包 host → 将来扩展 consume 为归档解包。
3. 版本历史 / 回滚 → 将来加 `active` / 归档表。
