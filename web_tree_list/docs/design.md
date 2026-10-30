# Tree List View — 设计

## 架构

`js_class` 变体：展开 `listView`，只替换 `Model` 与 `Renderer`，其余（ArchParser、
Controller、buttonTemplate、props）沿用 list。

- `tree_list_view.js`：`{ ...listView, Model: TreeListModel, Renderer: TreeListRenderer }`，
  注册到 `views` registry 的 `tree_list` 键。
- `tree_list_model.js`：`TreeListModel extends RelationalModel`。检测 tree 模式；
  tree 模式下加载 "false 组"（`parent_id=false` 的记录）作为树根，并暴露
  `treeRoots` / `treeParentMap`。
- `tree_list_renderer.js`：`TreeListRenderer extends ListRenderer`。tree 模式用自定义
  `Rows` 模板递归渲染，非 tree 模式回退到原生 `web.ListRenderer.Rows`。
- `tree_list_renderer.xml`：`Rows`（分支）、`Node`（递归）、`GroupRow`（缩进折叠头）、
  `LeafRow`（叶子字段行）四个模板。

## 关键机制

### 自动检测

`groupBy.length === 1 && field.type === "many2one" && field.relation === resModel`
即进入 tree 模式。

### 树从扁平分组结果重建（不额外 RPC、不递归 read_group）

原生 `RelationalModel` 的扁平 groupBy 结果已经含：每个父值一个 `Group`（`value` =
父记录 id、`displayName` = 名字、`count` = 直接子数、`list` = 懒加载子记录），外加
一个 `value === false` 的 "None" 组（根记录）。树由此**自顶向下**重建：

- 根 = false 组懒加载出的记录；
- 对某记录，`treeParentMap.has(record.resId)` 判它是否也是父（即存在对应 `Group`）；
- 是父 → 渲染分组头，展开后递归其 `group.list.records`；否则 → 叶子行。

因此无需 `id:array_agg` 额外读组，也无需服务端新方法；折叠与子记录懒加载全部复用
list 原生的 `Group.isFolded` / `Group.toggle()`。

## 被否决的方案

- **用 `read_group` 递归**：`groupby=['parent_id','parent_id.parent_id']` 是"按记录父
  分一层 + 按记录祖父分一层"两个独立维度，产出重复而非树；且对"X 的子节点"再
  `read_group(groupby=[parent_id])` 只会得到唯一 group "X"。无法表达无界递归。
- **新增后端 view type `tree_list`**：需要 `ir.ui.view` type selection、`view_mode`
  selection、`_get_view_info`、RNG、arch 校验 + 前端 parser 接受新根标签，改动大；
  用户只想要"增强的 list"，`js_class` 变体零后端改动即可满足。
- **合成 `Group`/`DynamicGroupList` 树**：其懒加载会再次 `read_group`，须连同
  `DynamicGroupList._load` 一起重写，耦合过深；自定义轻量树 + 复用行渲染更稳。

## 红线

1. tree 模式只能由"单个自引用 `many2one` groupBy"触发，不得改变非 tree 模式的原生
   list 行为——非 tree 分支必须原样回退到 `web.ListRenderer.Rows`。
2. 树重建必须复用 `RelationalModel` 的扁平分组结果（`Group` / `false` 组），不得
   额外发 `id:array_agg` 或新增后端方法。
3. 折叠/子记录懒加载必须走 `Group.isFolded` / `Group.toggle()`，不得自造第二套
   折叠状态。
