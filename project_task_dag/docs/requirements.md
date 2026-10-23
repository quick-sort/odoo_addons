# project_task_dag — 业务需求

## 目标

把项目里 task 的依赖关系（`depend_on_ids` / `dependent_ids`）可视化成一张有向
无环图（DAG），作为 `project.task` 的一个 view type，在任务列表里切换查看。

## 范围

- 依赖 `project` + `web_dag`；为 `project.task` 提供 `get_dag_data(domain)` 数据源。
- 把 `dag` 视图挂到任务列表 action（项目任务 + 全部任务）。

## 不做

- 不自己实现前端：渲染都在 `web_dag`，本模块只供数据与视图 wiring。
- 不做依赖编辑（增删 `depend_on_ids` 仍走 task form）。
