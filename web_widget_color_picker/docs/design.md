# Web Widget Color Picker — 设计

## 组件

`static/src/fields/color_picker/color_picker_field.js` 注册字段 widget
`compact_color_picker`（`supportedTypes: ["integer"]`），模板
`color_picker_field.xml` 复用 `@web/core/colorlist/colorlist` 的 `ColorList`：

- `canToggle="!props.readonly"`：收起态只渲染当前色点，点击展开；
- `colors` 为 0–11 的颜色索引；
- `selectedColor` 取 `record.data[name] || 0`；
- `onColorSelected` 调 `record.update({[name]: index}, {save: true})`，
  保证列表里点击即落库。

## 关键取舍

- **不注册为 `color_picker`**：registry 是全局的，覆盖核心名会改变所有使用
  核心 widget 的视图（CRM 阶段、假期类型等）。
- **选中即保存**：核心 `color_picker` 在列表只改内存不写库，正是本模块要解决
  的问题；与核心 `kanban_color_picker` 的即时保存行为保持一致。
- **复用 `ColorList`**：不复制色板实现，只包一层保存逻辑。

## 依赖

仅 `web`。
