# Project Task DAG — 设计

## 目标

把 `project.task` 的依赖关系（`depend_on_ids` / `dependent_ids`）可视化成一个有向无环图（DAG）。

## 方案选型

- **client action 而非自定义 view type**：一次性可视化，不需要声明式 arch 复用；
  view type 要走完整 View/Controller/Renderer 生命周期，成本高一个数量级。
- **自研 SVG 分层布局而非引入图库**：零外部依赖、自包含。依赖被
  `_check_no_cyclic_dependencies` 强制成 DAG，最长路径分层（Kahn 拓扑）即可稳定
  布局。后续要拖拽/缩放再换 Cytoscape.js + dagre。

## 数据契约

`project.task.get_dependency_graph_data(project_id)` 返回
`{nodes: [{id, name, state}], edges: [{source, target}]}`。
edge 方向 = 前置（`depend_on_ids`）→ 被阻塞的 task，即箭头 A → B 表示 "A 阻塞 B"。

## 布局

最长路径分层（Kahn 拓扑排序 + depth 传播），层内按 id 排序，左→右摆放；edge 从源
节点右缘连到目标节点左缘，带箭头。节点按 state 着色（done/canceled/open）。

## 权限

`get_dependency_graph_data` 只读，内部 `search` 受 access right 约束，无新增越权面。

## 入口

project 表单 `button_box` 加 `oe_stat_button`，`type="object"` 调
`project.project.action_open_task_dependency_graph()`，该方法返回 `ir.actions.client`
（`tag="task_dependency_graph"`）并在 context 里显式绑定 `active_id`（当前 project id）。

不用 `type="action"` 按钮：它不会可靠地把 `active_id` 传进 client action 的 context
（`context="{'active_id': id}"` 到组件里读到的是空），导致 `get_dependency_graph_data`
收到空 `project_id` 而抛 `TypeError`。显式在 Python 方法里绑定 id 与 Odoo 原生
`stock_forecasted` 的做法一致。
