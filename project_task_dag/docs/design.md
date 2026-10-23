# Project Task DAG — 设计

## 目标

把 `project.task` 的依赖关系（`depend_on_ids` / `dependent_ids`）可视化成一个有向无环图
（DAG），做成可复用的 view type `dag`，按 `web_gantt` + `project_task_gantt` 的拆分方式分成
两个模块。

## 模块拆分

- **`web_dag`**（通用，依赖 `web`）：注册 view type `dag`（`ir.ui.view.type` 与
  `ir.actions.act_window.view.view_mode` 各加 `selection_add`），前端 `DagView` /
  `DagController` 注册进 `registry.category("views")`，自研 SVG 分层布局，零外部前端依赖。
- **`project_task_dag`**（项目扩展，依赖 `project` + `web_dag`）：只提供数据源
  `project.task.get_dag_data(domain)`、`<dag/>` 视图记录、把 `dag` 挂进 project 任务列表
  action 的 `act_window.view`。

## 数据契约

`project.task.get_dag_data(domain=None)` 是 `@api.model`，返回
`{nodes: [{id, name, state}], edges: [{source, target}]}`。edge 方向 = 前置
（`depend_on_ids`）→ 被阻塞的 task，即箭头 A → B 表示 "A 阻塞 B"。只保留两端都在 recordset
内的边（范围由 domain 决定）。节点 `state` 在后端归一化成 `done/canceled/open` 三档，让
`web_dag` 不感知 `project.task` 的具体 state 取值。

方法必须是 `@api.model`：前端 `orm.call("project.task", "get_dag_data", [], {domain})`
只传 kwargs、不带 record ids；非 `@api.model` 方法经 `call_kw` 会把第一个位置参数当成 ids
而报错。

## 布局

最长路径分层（Kahn 拓扑排序 + depth 传播），层内按 id 排序，左→右摆放；edge 从源节点右缘连
到目标节点左缘，带箭头。节点按 state 着色（done=绿 / canceled=灰 / open=蓝）。

## 权限

`get_dag_data` 只读，内部 `search` 受 access right 约束，无新增越权面。

## 入口

作为 view type 挂到任务列表 action（`project.act_project_project_2_project_task_all` 与
`project.action_view_all_task`）的 `view_mode`，用户在视图切换里选「DAG」。无 project 表单
按钮、无 client action。
