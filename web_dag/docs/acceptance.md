# web_dag — 验收标准

QC 唯一依据。每个功能点至少一个测试（前端渲染项为手工验收）。

1. **view type 注册**：`ir.ui.view.type` selection 含 `dag`。
   → `tests/test_view_type.py::test_view_type_selection_has_dag`
2. **act_window.view 支持**：`ir.actions.act_window.view.view_mode` selection 含
   `dag`。→ `test_act_window_view_mode_has_dag`
3. **视图元信息**：`get_view_info()` 返回 `dag`，`display_name=DAG`、
   `multi_record=True`。→ `test_get_view_info_exposes_dag`
4. **渲染（手工）**：act_window 的 `view_mode` 含 `dag` 时，前端能切到 DAG 视图，
   显示节点/边，点击节点打开 form。
