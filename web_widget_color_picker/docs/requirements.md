# Web Widget Color Picker — 需求

## 问题

Odoo 19 自带的 `color_picker` 字段 widget 在可编辑列表中会平铺全部颜色，
且选中后只更新内存记录、不落库；`kanban_color_picker` 始终平铺全部颜色，
并按 `color` 字段判断当前值。两者都不适合给任意整数字段（例如任务甘特条
颜色 `gantt_color`）在列表和表单中选择颜色。

## 范围

- 提供字段 widget `compact_color_picker`，适用于 `integer` 字段
  （0–11，Odoo 标准颜色索引）。
- 收起态只显示当前颜色；点击展开 12 色色板。
- 选中颜色后立即写库，列表与表单行为一致。
- 只读字段不可展开、不可修改。

## 不做

- 不覆盖核心 `color_picker` / `kanban_color_picker` 的注册名。
- 不处理非整数颜色（如 CSS 字符串颜色、自定义色值）。
- 不引入第三方 JS 依赖。
