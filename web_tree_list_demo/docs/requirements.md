# Tree List View Demo — 需求

## 问题

`web_tree_list` 是纯前端视图，需要一个可安装、可浏览器验证的演示载体：一个带自引用
`parent_id` 的模型 + 使用 `js_class="tree_list"` 的列表视图 + 多级演示数据。

## 范围

- 新增 `web_tree_list_demo.category` 模型：`name`、`parent_id`（自引用 many2one）、
  `child_ids`、`sequence`、`description`。
- 列表视图 `<list js_class="tree_list" default_group_by="parent_id">`，打开即呈现树。
- form 视图 + 菜单/动作入口。
- demo 数据：≥3 层树（根→子→孙），覆盖多分支。

## 不做

- 不做业务语义，只做 `web_tree_list` 的演示与验证。
- 不定义新的 Python 业务逻辑。
