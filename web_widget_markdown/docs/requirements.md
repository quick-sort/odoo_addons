# 需求（requirements）

## 背景

Odoo 自带的 `html` field widget 是富文本编辑器；但有些内容（文档、注释、AI 输出）
更适合以 markdown 源码存储、渲染展示。

## 要解决什么

在 form 视图里给 `fields.Text`（markdown 源码）提供一个专用 widget：

- 编辑时是等宽 textarea，可一键切换成渲染预览；
- 只读时始终渲染 markdown 为 HTML。

## 范围 / 边界

- 支持字段类型：`text`、`char`（内容为 markdown 源码）。
- 编辑：源码 textarea + 「Edit / Preview」二态切换。
- 只读：markdown → HTML 渲染。

## 明确不做

- 不引入后端 Python markdown 依赖。
- 不做 WYSIWYG 工具栏、分屏、图片上传、服务端渲染。
