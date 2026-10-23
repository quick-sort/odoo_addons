========
DAG View
========

通用的 DAG（有向无环图）view type ``dag``：把宿主模型 ``get_dag_data(domain)``
返回的 ``{nodes, edges}`` 渲染成一张节点-连线图。

- 不依赖 ``project``，任意模型实现 ``get_dag_data`` 即可复用。
- 自研 SVG 分层布局，零外部前端依赖。
- 只读：箭头 A → B 表示 "A 阻塞 B"，点击节点打开对应记录 form。

配套项目示例见 ``project_task_dag``。
