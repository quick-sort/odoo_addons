# Web Gantt — 设计

## 架构

- `gantt_view.js`：向 `views` registry 注册 `gantt` 视图；`GanttController` 负责
  工具栏、加载数据、写回拖拽结果；`GanttView` 提供标准 Layout 外壳。
- `gantt_renderer.js`：纯 canvas 自绘。所有可视元素（网格、表头、任务条、左侧
  列表、滚动条、今天线）都在一次 `drawGantt()` 中绘制。
- `gantt_view.xml`：OWL 模板与工具栏按钮。

数据由模型的 `get_gantt_data(domain, group_by)` 提供，结构为
`[{id, name, tasks: [{id, name, start_date, end_date, depth, parent_id, assignees, ...}]}]`。
任务数组必须是 DFS 前序，且 `depth` 表示树深度。

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
