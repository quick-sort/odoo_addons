# Tree List View Demo — 验收标准

## 功能点

1. **模型可建树**：`parent_id`/`child_ids` 双向关系正确。
   - 验收：`tests/test_category.py::test_tree_structure` 通过。

2. **模块干净装载**：`-u web_tree_list_demo --stop-after-init` 退出码 0（拉入
   `web_tree_list`，其列表视图 arch 通过校验）。
   - 验收：安装无报错。

3. **demo 数据 ≥3 层**：菜单"Tree List Demo"打开后，按 `parent_id` 分组呈现
   Root → Child → Grandchild 的多级折叠树。
   - 验收：浏览器中可见 3 层分组头，可逐级折叠。

4. **叶子字段渲染**：叶子行显示 name（description 为 optional 列）。
   - 验收：叶子行 name 正常显示。
