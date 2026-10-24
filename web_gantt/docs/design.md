# Web Gantt — 设计

## 架构

- `gantt_view.js`：向 `views` registry 注册 `gantt` 视图；`GanttController` 负责
  工具栏、加载数据、写回拖拽结果；`GanttView` 提供标准 Layout 外壳。
- `gantt_renderer.js`：纯 canvas 自绘。所有可视元素（网格、表头、任务条、左侧
  列表、滚动条、今天线）都在一次 `drawGantt()` 中绘制。
- `gantt_view.xml`：OWL 模板与工具栏按钮。

数据由模型的 `get_gantt_data(domain, group_by)` 提供：

```
{
  groups: [{id, name, tasks: [{id, name, start_date, end_date, depth, parent_id, assignees, ...}]}],
  markers: [{date: "YYYY-MM-DD", label, color?, description?}],
}
```

任务数组必须是 DFS 前序，且 `depth` 表示树深度。为向后兼容，直接返回 groups
数组也合法（视为 `markers: []`）。

## 日期映射 mixin（`gantt.mixin`）

模型 `_inherit = ["<model>", "gantt.mixin"]` 并实现
`_gantt_date_fields() -> (start_field, stop_field)` 后，即可用
`gantt_date_start` / `gantt_date_stop` 作为视图的 `date_start` / `date_stop`：

- 两个别名都是**非存储** computed+inverse 字段，不产生数据库列；
- 计算依赖用 `@api.depends(lambda self: self._gantt_date_fields())`，由实现方决定依赖，
  mixin 自身（抽象模型）返回 `()`；
- 两个别名共享一个 inverse，Odoo 每次写入只调用一次；inverse 只把变化的值通过
  `write()` 写回后端字段，因此下游模型的 `write()` 覆盖会照常触发；
- 别名的 `search` 把 domain 原样转给后端字段，因此别名可用于过滤；
- `default_get` 把 Gantt 工具栏 “New” 传入的 `default_gantt_date_start` 映射到后端
  start 字段，并**移除**别名键：否则 create 会写入别名，其 inverse 反过来覆盖用户
  明确传入的后端值。

mixin 只负责日期映射，**不提供** `get_gantt_data`；数据载荷仍由各模型实现。

## 标记线（markers）

- 模型通过 `markers` 数组提供额外的竖向标记线（如里程碑日期）；web_gantt 不解释
  业务语义，只按 `date` / `label` / `color` / `description` 渲染。
- `YYYY-MM-DD` 由前端按**本地时区**构造（`new Date('YYYY-MM-DD')` 按 UTC 解析，
  负时区会偏一天）；非法日期/颜色被忽略或回退到默认主色。
- 绘制在表头之后、左侧列表之前，并裁剪在时间轴区域内：1.5px 虚线 + 常显标签
  （两条 lane 错开，放不下时省略标签但保留竖线）；悬停竖线或标签显示
  label / 日期 / description。
- marker 日期参与可视范围与导出范围计算；PNG 导出自动包含标记线，CSV 仍只含任务。

## 时间尺度

| scale | 一个单元格 | 表头上层 | 表头下层 |
|---|---|---|---|
| week | 1 周 | 月 | W<周数> |
| month | 1 天 | 月 | 日 |
| quarter | 1 季度（3 个月） | 年 | Q1–Q4 |
| year | 1 个月 | 年 | 月 |

`dateToX()` / `xToDate()` 与各尺度的 `cellWidth` 系数一一对应；拖拽改期按尺度
吸附（周按天、月按天、季度按 3 个月、年按 1 个月）。新增尺度必须同时修改：
`cellWidth`、`getTotalUnits`、`drawGrid`、`drawHeader`、`dateToX`、`xToDate`、
拖拽分支、`handleVerticalTimeScaleNavigation`、`handleNavigate`。

## 行模型与折叠

`getRows(data)` 把分组行与任务行展开为一维数组，屏幕绘制、命中判定、滚动高度
共用这一份结果。折叠状态保存在渲染器的 `state.collapsedIds`：

- 先根据同组任务的 `parent_id` 计算每个任务是否有子任务；
- 任务按 DFS 前序排列，折叠某任务后，后续所有 `depth` 更深的行都跳过，直到出现
  同级或更浅的行；
- 左侧列表在父任务前绘制三角箭头，并记录命中区 `row._caretRect`；点击箭头切换
  折叠，点击行其余位置仍打开表单。

折叠只影响显示，不修改数据。

## 左侧列表

- 任务名前有颜色点，名称右侧右对齐显示 assignee（`assignees` 字符串数组，后端
  提供），空间不足时分别截断。
- 行高 `baseCellHeight = 32`，任务条上下各留 4px。

## 导出图片

`exportImage()` 不截取屏幕 canvas，而是新建离屏 canvas：

- 日期范围取所有任务的最早开始 / 最晚结束，并按当前尺度对齐到整周/月/季度/年；
- 行集合使用完整的 `getRows()`（含折叠状态）；
- 临时把 `scrollX/scrollY` 归零、清除 hover 状态，复用 `drawLayers()` 绘制；
- 宽度上限 16000px：超长时先降低缩放系数，再降低输出像素比，保证落在浏览器
  canvas 安全尺寸内；
- 输出 PNG 并下载，随后恢复滚动/缩放状态并重绘屏幕。

## 被否决的方案

- **DOM 行渲染**：行数多时性能差，且与 canvas 时间轴对齐复杂；保持全 canvas。
- **直接 canvas.toDataURL 截屏**：只能得到当前视口，无法导出“整张图”。
- **引入第三方 Gantt 库**：需要额外依赖与打包流程，现有自绘实现已覆盖需求。
