# InfoHub RSS Channel — 系统设计

## 渠道扩展

沿用 core 的扩展点（`infohub.channel` collection）：

- `infohub.fetch.rss` —— `fetch_news()` 出网 + 解析，返回 `(body, entries)`
- `infohub.content.rss` —— 把解析出的 raw dict 映射成 subject/date/source/url/
  content

模型侧：`_inherit = "infohub.channel"`，`selection_add=[("rss", "RSS / Atom")]`，
加一个 `rss_url` 字段（渠道专属字段不进 core）。

## 解析设计：通用而非按发布方特判

用标准库 `xml.etree.ElementTree`，不用 `feedparser`。每个 `<item>`/`<entry>`
的子元素按 **local tag name** 收进 `raw_data`：

- 命名空间被剥离（`dc:creator` → `creator`）
- 重复 tag 收成列表，`<link>` 优先取 `rel="alternate"`（Atom 有多个 link）
- Media RSS 的 `content`（缩略图）跳过，避免误当正文
- 三种布局（RSS 2.0 的 `<channel>` 嵌套、RDF 的兄弟节点、Atom 的 `<entry>`）
  都靠"按 local name 全树找"统一处理，不写布局分支

这一设计的收益：发布方私有字段（`prn:industry` 等）原样保留，`filter_domain`
能匹配它们，却不需要为任何一家写特判代码。

## SSRF 与出网

复用 core 的 `url_guard`：

- 保存期：`assert_url_allowed(resolve=False)` 只查 scheme/主机名/字面 IP，
  不发 DNS（避免把 DNS 引入数据库写路径）
- 请求期：`allow_redirects=False` 手工跟跳，每一跳都 `resolve=True` 复检
- 响应体积上限 10 MiB；feed reader User-Agent 优先、浏览器 UA 兜底（不同发布方
  的 bot 过滤策略相反）

## 被否决的方案

| 方案 | 否决理由 |
|---|---|
| 用 `feedparser` | 会把条目扁平成固定字段，发布方私有字段丢失，`filter_domain` 就废了。标准库 ElementTree 已够用。 |
| 按发布方写解析分支 | 来源一多就爆炸，违背"新增渠道不改代码"的初衷。 |
| 复用旧 legacy 的三轴 transport/mapper | 旧设计已整体否决，见 core design.md。 |
