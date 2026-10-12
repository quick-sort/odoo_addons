# 设计（design）

## 架构

纯前端 field widget，注册进 `fields` registry 的 `markdown` 名字。

- `static/lib/marked/marked.min.js` — vendored `marked` v4.3.0（MIT），UMD 构建，
  挂到 `window.marked`，经独立 bundle `web_widget_markdown.assets_lib` 用 `loadBundle`
  按需加载（仿 `web_widget_mermaid`）。
- `markdown_field.js` — OWL 组件 `MarkdownField`；源码用 `useInputField` 绑定 textarea，
  预览用 `marked.parse` + `DOMPurify.sanitize` + `markup()`。

## 关键取舍

- 选 `marked` 而非自写解析器：成熟、CommonMark 兼容、极小、MIT。
- 用 Odoo 自带的 DOMPurify（已在 `web.assets_backend`）做消毒，不额外 vendor。
- 预览切换是「源码 / 预览」二态而非分屏：保持轻量，符合选定形态。

## 安全

渲染链路：`marked.parse(md)` → `DOMPurify.sanitize(html)` → `markup(html)` → `t-out`。
绝不把未经消毒的 HTML 交给 `t-raw`。

## 被否决的方案

- EasyMDE 完整编辑器：功能重、vendor 体积大，与本 addon「轻量」定位不符。
- 服务端渲染 markdown：引入后端依赖与序列化开销，纯前端已够用。
