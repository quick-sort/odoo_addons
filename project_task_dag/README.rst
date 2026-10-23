=================
Project Task DAG
=================

把项目里 task 的依赖关系（``depend_on_ids`` / ``dependent_ids``）渲染成一张有向图（DAG），
做成可复用的 view type ``dag``。

两模块
======

- ``web_dag``：通用 DAG view（注册 view type ``dag`` + 前端 SVG 分层布局），不依赖 ``project``。
- ``project_task_dag``：项目扩展，提供数据源 ``project.task.get_dag_data(domain)`` 并把
  ``dag`` view 挂进 project 任务列表。

用法
====

- 依赖 ``project``、``web_dag``；无新增 Python 依赖。
- 打开 project 的任务列表，在视图切换里选「DAG」：箭头 A → B 表示 "A 阻塞 B"；点击节点打开
  对应 task；节点按状态着色（完成=绿、取消=灰、进行中=蓝）。
- demo 数据（``demo/task_dependency_demo.xml``）提供一个「Product Launch」项目及 12 个带
  依赖的 task，用 demo data 加载即可演示。

详细设计见 ``docs/design.md``。
