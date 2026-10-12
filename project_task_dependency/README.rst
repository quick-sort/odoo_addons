=============================
 Project Task Dependency Graph
=============================

把项目里 task 的依赖关系（``depend_on_ids`` / ``dependent_ids``）渲染成一张有向图
（DAG）。自研 SVG 分层布局，零外部前端依赖。

用法
====

- 依赖 ``project``；无新增 Python 依赖。
- 在 project 表单的 smart button 区点「Dependencies」打开图：箭头 A → B 表示
  "A 阻塞 B"；点击节点打开对应 task；节点按状态着色（完成=绿、取消=灰、进行中=蓝）。
- demo 数据（``demo/task_dependency_demo.xml``）提供一个「Product Launch」项目及
  12 个带依赖的 task，用 demo data 加载即可演示。

详细设计见 ``docs/design.md``。
