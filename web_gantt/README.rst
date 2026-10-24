==============
 Gantt View
==============

通用的 Gantt 视图（视图类型 ``gantt``），纯 canvas 绘制，可在任意带起止日期的
模型上使用。

用法
====

- 依赖 ``web``；无额外 Python 依赖。
- 在模型上定义视图：

.. code-block:: xml

    <gantt string="My Gantt" date_start="date_start" date_stop="date_stop"/>

- 可选：继承 ``gantt.mixin``，把两个**非存储**日期别名映射到模型已有字段，
  避免为 Gantt 新增冗余日期列：

.. code-block:: python

    class MyModel(models.Model):
        _name = "my.model"
        _inherit = ["my.model", "gantt.mixin"]

        def _gantt_date_fields(self):
            return ("my_start_field", "my_end_field")

.. code-block:: xml

    <gantt string="My Gantt" date_start="gantt_date_start" date_stop="gantt_date_stop"/>

  别名可读、可写（拖动写回后端字段）、可搜索；Gantt 的 New 按钮传入的
  ``default_gantt_date_start`` 会映射到后端 start 字段。

- 可选竖向标记线：``get_gantt_data`` 返回 ``{groups, markers}``，其中 ``markers`` 为
  ``[{date: "YYYY-MM-DD", label: "...", color: "#rrggbb", description: "..."}]``。
  标记线常显标签（密集时错行/省略标签），悬停显示名称、日期与说明；PNG 导出包含
  标记线，CSV 仍只含任务。直接返回旧的 groups 数组仍兼容（视为无标记线）。

- 顶部工具栏提供 New、Refresh、Export（CSV）、Export Image（PNG）。
- 时间尺度为 Week / Month / Quarter / Year。
- 左侧列表中有子任务的行显示折叠箭头；任务名右侧显示 assignee（模型需在
  ``get_gantt_data`` 中提供 ``assignees`` 字段）。
- 可编辑模式下可拖动任务条改期；滚轮横向/纵向滚动，Ctrl+滚轮缩放，
  Shift+滚轮竖向滚动。

注意
====

- Export Image 导出整张图（全部行 + 完整时间范围），而不是当前视口截图。
- 折叠只影响显示，不会修改任务层级。

详细设计见 ``docs/design.md``，验收标准见 ``docs/acceptance.md``。
