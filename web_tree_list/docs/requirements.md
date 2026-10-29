# Tree List View — 需求

## 问题

标准 list view 的 `group_by` 底层是 `read_group`，对自引用 `many2one` 字段
（如 `parent_id`）只能产生**一级**分组头：每个父值对应一个扁平 group，group
之间不嵌套。而 `parent_id` 本身可能是任意深度的树，用户需要"按父字段分组时，
自动跟随树结构产生多级可折叠层级"。

## 范围

- 新增 `tree_list` 视图，以 `js_class="tree_list"` 形式挂在普通 `<list>` 视图上
  （不改动后端 view type，零 RNG/零数据库改动）。
- 自动检测：当当前 groupBy 是**单个**指向本 model 的 `many2one` 自引用字段时，
  进入 tree 模式，按父树递归渲染多级分组头；否则退化为普通 list，行为与原生
  list 完全一致。
- 每级分组头可独立折叠/展开，折叠状态沿用 list 原生 group 折叠机制。
- 叶子记录用 list 原生字段渲染（widget、formatter、decoration）。
- 搜索/过滤、排序、多选沿用 list 原生能力。

## 不做

- 不做 tree 模式下的行内编辑（`editable="top/bottom"` 的 edit toggle）；tree 模式
  v1 只读。
- 不做多字段 groupBy 叠加（如 `[department_id, parent_id]`）下的递归；仅"单个
  自引用 groupBy 字段"触发。
- 不做拖拽重排父级（reparent）。
- 不在前端用 `read_group` 递归，也不新增后端 `hierarchy_read` 类方法（复用现有
  扁平分组结果重建树）。
