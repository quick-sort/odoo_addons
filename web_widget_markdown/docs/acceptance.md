# 验收（acceptance）

## 功能点

### A1 只读渲染
只读时字段渲染为 markdown 对应的 HTML（标题、加粗、列表、代码块等）。

### A2 编辑默认源码
编辑时默认显示等宽 textarea，内容为字段的 markdown 源码。

### A3 预览切换
点击「Preview」在编辑态内显示渲染结果；点击「Edit」回到源码 textarea。

### A4 写回
在 textarea 修改后，值正确写回 `record`（blur/change 触发）。

### A5 安全
渲染 HTML 经 DOMPurify 消毒，`<script>` 等危险标签不生效。

## 自动化测试覆盖说明

`tests/` 覆盖**静态契约**：manifest 无 `description`、assets 声明、vendored lib
存在、widget 注册名、README 存在。

A1–A5 是前端行为，当前仓库无 JS 测试运行器，靠 `node --check` / `xml.dom.minidom`
静态校验 + 浏览器手动 QA 验收。
