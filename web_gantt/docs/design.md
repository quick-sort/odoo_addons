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

- `progress`（若模型提供）为 **0–100 百分比**：渲染器据此画任务条内的进度条，
  并按 100% 截断（超出部分不绘制，供 over-allocated 场景兜底）；tooltip 与 CSV
  导出原样展示该值。
- 任务条与左侧颜色点使用**主题主色**（`--bs-primary`，回退 `--o-cc1-btn-primary`
  → `#714B67`），随 `web_company_color` 等主题配置变化，不再使用硬编码调色板。
  进度按「浅色未完成轨道 + 实色已完成」绘制：整条为任务色的浅色 tint（带主色细
  边框），已完成部分叠加实色，未完成部分保持浅色，使进度一眼可辨。

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

尺度名取该视图的**最小单元格单位**，表头上层只是更粗的分组：

| scale | 一个单元格 | 表头上层 | 表头下层 |
|---|---|---|---|
| day | 1 天 | 月 | 日 |
| week | 1 周 | 月 | W<周数> |
| month | 1 个月 | 年 | 月 |
| quarter | 1 季度（3 个月） | 年 | Q1–Q4 |

表头分两层：上层按组**合并单元格**（Day/Week 按月、Month/Quarter 按年），标签在
可见范围内居中，组边界画竖线；下层为最小日期单元格（天/周/月/季度），逐格画竖线；
两层之间有水平分隔线，竖线与图表网格使用同一组坐标。

`dateToX()` / `xToDate()` 与各尺度的 `cellWidth` 系数一一对应；拖拽改期按尺度
吸附（天/周按天、月按 1 个月、季度按 3 个月）。切换尺度后视图重新居中到
today（cellWidth 变化会让旧的横向滚动偏移失效）。新增尺度必须同时修改：
`cellWidth`、`getTotalUnits`、`drawGrid`、`drawHeader`、`dateToX`、`xToDate`、
拖拽分支、`handleVerticalTimeScaleNavigation`、`handleNavigate`。

## 可选载荷字段

除 `groups` / `markers` 外，任务可带 `predecessor_ids`（前置任务的 id 数组）。
渲染器只在两端任务都处于当前可见行时才画依赖箭头。

## 任务依赖

- 工具栏 Dependencies 按钮切换 `showDependencies`。
- 每个任务的 `predecessor_ids` 指向其前置任务；箭头从前置任务条的右端（完成）
  连到后继任务条的左端（开始），即完成-开始关系。
- 同一任务因多分组（如按负责人）重复出现时，以第一条可见行上的任务条为锚点；
  被折叠隐藏的任务不画箭头。
- 箭头画在任务条之上并裁剪在时间轴区域内；屏幕绘制与 PNG 导出共用。
- 后继开始时间不晚于前置结束时间（任务重叠或完全同起止）时，箭头从前置右端
  下折到两行之间的间隙，沿间隙横向穿过，再绕到后继任务条左侧，从其开始边缘
  由左向右接入；不穿过任务条本身。

## 里程碑显隐

- 工具栏 Timeline 多选下拉框只列当前载荷里的 marker（里程碑）。
- 标记线默认全部显示。下拉框记录被取消勾选的 marker 键（`date|label`），渲染器
  只接收可见 marker，因此新出现的里程碑自动显示，已消失的键在刷新时剔除。
- 下拉框顶部的 Select all 复选框全选/取消全选：全部可见时为勾选态，点击后清空
  隐藏集合（全部显示）；存在任意隐藏项时为未勾选态，点击后隐藏全部里程碑。
- 界面不额外占用行高，也不在表头上方增加汇总带；可见 marker 直接画在图表内。

## 任务配色

任务的 `color` 字段支持两种形态：正整数为 Odoo 色板索引（1–11，取自
`$o-colors`），`"#rrggbb"` 为任意颜色；缺省或 0 回退到主题主色。任务条使用
「浅色轨道 + 实色进度」：轨道与进度都由该颜色派生，左侧列表色点同色，保证同一
任务在各处颜色一致。

## 日期间隔线

`getScaleBoundaries()` 按当前尺度（天/周/月/季度）返回每个日期单元格的 x 坐标；
表头与图表网格都使用同一组坐标绘制竖向间隔线，保证两者对齐且随横向滚动同步。

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
- 导出高度为 `headerHeight + 行数 × cellHeight`，依赖箭头与当前可见的
  里程碑标记线随 `drawLayers()` 一并输出；
- 临时把 `scrollX/scrollY` 归零、清除 hover 状态，复用 `drawLayers()` 绘制；
- 宽度上限 16000px：超长时先降低缩放系数，再降低输出像素比，保证落在浏览器
  canvas 安全尺寸内；
- 输出 PNG 并下载，随后恢复滚动/缩放状态并重绘屏幕。

## 被否决的方案

- **DOM 行渲染**：行数多时性能差，且与 canvas 时间轴对齐复杂；保持全 canvas。
- **直接 canvas.toDataURL 截屏**：只能得到当前视口，无法导出“整张图”。
- **引入第三方 Gantt 库**：需要额外依赖与打包流程，现有自绘实现已覆盖需求。
