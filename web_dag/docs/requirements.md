# web_dag — 业务需求

## 目标

提供一个**通用、可复用**的 DAG（有向无环图）view type `dag`：把任意 Odoo 模型
提供的一张节点-连线图渲染出来，不绑定某个具体业务模型。

## 范围

- 注册 view type `dag`，可在任意 `act_window` 的 `views`/`view_mode` 里使用。
- 前端负责渲染（节点、带箭头的边、按 state 着色、点击打开 form），自研 SVG 分层
  布局，零外部前端依赖。
- 数据由**宿主模型**通过 `get_dag_data(domain)` 提供，`web_dag` 不拥有数据。

## 不做

- 不做图编辑（增删节点/边、拖拽改依赖）。
- 不感知宿主模型的具体字段：节点只看 `id/name/state`，边只看 `source/target`，
  `state` 必须是 `done/canceled/open` 三档之一。
- 不依赖 `project`，不与任何具体 addon 耦合。
