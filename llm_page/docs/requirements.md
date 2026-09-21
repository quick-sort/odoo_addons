# LLM Page — 业务需求

## 要解决的问题

让 agent（Claude Code / OpenClaw 等）生成的静态 HTML（含 JS）通过 Odoo website
对外 host，并受「指定用户组」授权 + 「三级审核」流程管控。

典型场景：

1. agent 产出静态页（仪表盘、图表、mermaid 图、报告等），经 storage MCP
   上传后，调用本模块工具把它登记为一个待审核页面。
2. 审核员在后台预览内容，通过后发布；发布页仅授权组用户可访问。
3. 审核员可驳回（填原因）或下架。

## 范围

**做**：

- 承接 `storage_backend_mcp` 的暂存上传（`file_id`），消费 HTML 内容生成页面
- 提供 MCP 工具：创建草稿、列出、查状态、提交审核
- 三级审核状态机：`draft → pending → published`，另含 `rejected` 驳回态
- 每页指定访问组（`group_id`），controller 强制鉴权
- 用 `website.layout` 主题包裹渲染（页眉/页脚/主题）
- 后端视图（表单/列表/看板/菜单）与审核操作按钮
- 上传来源审计（backend / sha256 / size）

**不做**：

- 不做 MCP 服务端（那是 `llm_mcp_server` 的事；本 addon 只贡献 `llm.tool` 行）
- 不做在线富文本编辑器（内容是 agent 产物，后台只读预览，不二次编辑）
- 不把页面纳入网站 sitemap / SEO 索引（授权页面不外泄）
- 不做多文件 / 资源包 host（单页单 HTML）
- 不做版本历史 / 回滚（最小可用）

## 非功能要求

1. **默认支持 JS**：HTML 以原始形态存储与渲染（不 sanitize），`<script>` /
   `<style>` 可正常运行。
2. **依赖隔离**：仅依赖 `website` + `storage_backend_mcp`，零新增 Python 依赖。
3. **离线可测**：不联网、无 API key、无 boto3 也能全量跑测试（mock 上传物）。
4. **安全边界清晰**：授权由「审核流程 + 指定用户组访问」双闸门兜底（见 design）。
