# Tree List View Demo — 设计

## 架构

- `models/category.py`：自引用模型，`parent_id`（ondelete cascade）+ `child_ids`。
- `views/category_views.xml`：tree 列表视图（`js_class="tree_list"` +
  `default_group_by="parent_id"`）、form、act_window、菜单。
- `demo/demo.xml`：3 层演示树。
- `tests/test_category.py`：验证自引用父子关系。

## 关键取舍

- 用 `default_group_by="parent_id"` 让视图**打开即进入 tree 模式**，免去手动点
  "Group by"，便于直接验证多级折叠。
- demo 数据放进 `demo/`（manifest 的 `demo` 键），不污染生产数据，`-i` 不带 demo
  时不加载。
