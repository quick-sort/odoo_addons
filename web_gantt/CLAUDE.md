# web_gantt — 开发约束（自动加载）

设计文档见 `docs/`，这是唯一要求来源，改代码前先读：

- `docs/requirements.md` — 业务需求与边界
- `docs/design.md` — 架构、时间尺度、行模型、导出
- `docs/acceptance.md` — 验收标准（QC 唯一依据）

红线（来自 design.md，勿违背）：

1. 图表主体是 canvas 自绘，没有 DOM 行节点；行内交互（折叠箭头、任务条）必须通过绘制时记录的命中区判定，不要依赖 DOM 事件委托。
2. 屏幕绘制与图片导出共用 `drawLayers()` 与 `dateToX()`；新增图层或时间尺度时必须同时验证 `exportImage()`（滚动归零、全量行、完整时间范围）。
3. `gantt.mixin` 的两个日期别名必须保持**非存储** computed+inverse；`_gantt_date_fields()` 在抽象模型上必须返回 `()`（registry 会解析依赖）。
