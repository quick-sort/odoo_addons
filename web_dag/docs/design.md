# web_dag — 设计

## 架构

两层：

- **后端**：`ir.ui.view.type` 与 `ir.actions.act_window.view.view_mode` 各加
  `selection_add` 注册 `dag`；`_get_view_info()` 暴露图标与 `multi_record`。
- **前端**：`DagView`（`Layout` 包装）+ `DagController` 注册进
  `registry.category("views")`，type = `dag`。Controller 调 `orm.call(resModel,
  "get_dag_data", [], {domain})` 取 `{nodes, edges}`，交给自研 SVG 分层布局渲染。

## 数据契约

宿主模型实现 `@api.model get_dag_data(domain=None)`，返回
`{nodes: [{id, name, state}], edges: [{source, target}]}`。
`state ∈ {done, canceled, open}`，边方向 A → B 表示 "A 阻塞 B"。

## 布局

最长路径分层（Kahn 拓扑排序 + depth 传播），层内按 id 排序，左→右摆放；边带箭头。
节点按 `state` 三档着色。

## 关键取舍

- **自定义 view type 而非 client action**：要的是可复用（塞进任意 act_window 的
  views）、可与其它视图并存，故走 view type；代价是要 View/Controller/Renderer
  生命周期样板。
- **方法驱动而非 record 派生**：数据由宿主模型 `get_dag_data` 给出，`web_dag`
  不读具体字段、不感知业务。与 `web_gantt`（`get_gantt_data`）同一契约风格。

## 被否决的方案

- 用标准 record plumbing 读 record、由 arch 指定 edge 字段：更通用但要处理字段
  发现/权限/懒加载，复杂度高于当前需求，否决。
- 引入 Cytoscape/dagre 图库：当前只需静态分层，自研零依赖即可；拖拽/缩放需要时
  再引入。
