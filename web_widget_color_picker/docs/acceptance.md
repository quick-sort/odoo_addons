# Web Widget Color Picker — 验收标准

| # | 功能点 | 验收标准 | 测试 |
|---|---|---|---|
| A1 | widget 注册 | `compact_color_picker` 注册于 fields registry，仅支持 `integer` | `test_widget_registered` |
| A2 | 资源与 manifest | `web.assets_backend` 声明 js/xml；manifest 不写 `description` | `test_manifest_has_no_description`、`test_assets_declared` |
| A3 | 模板 | 存在 `web_widget_color_picker.CompactColorPickerField` 模板并复用 `ColorList` | `test_template_present` |
| A4 | 收起/展开 | 初始只显示当前颜色；点击展开 12 色；选中后收起 | 人工检查 |
| A5 | 立即保存 | 表单或列表选中颜色后写库（刷新后仍保留） | 人工检查 |
| A6 | 只读 | `readonly` 字段不能展开、不能改值 | 人工检查 |

## 自动化测试覆盖说明

本仓库没有 JS 测试运行器；`tests/` 覆盖静态契约（注册名、支持类型、资产声明、
模板、README），A4–A6 由浏览器人工验收。
