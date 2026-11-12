# Tree List View — 设计

## 架构

`js_class` 变体：展开 `listView`，只替换 `Model` 与 `Renderer`，其余（ArchParser、
Controller、buttonTemplate、props）沿用 list。

- `tree_list_view.js`：`{ ...listView, Model: TreeListModel, Renderer: TreeListRenderer }`，
  注册到 `views` registry 的 `tree_list` 键。
- `tree_list_model.js`：`TreeListModel extends RelationalModel`。检测 tree 模式；
  tree 模式下加载 "false 组"（`parent_id=false` 的记录）作为树根，并暴露
  `treeRows`（预序扁平化的可见行）/ `treeParentMap`。
- `tree_list_renderer.js`：`TreeListRenderer extends ListRenderer`。tree 模式渲染
  `treeRows` 的扁平兄弟行；负责行深度 class、折叠箭头点击判定，非 tree 模式回退到
  原生 `web.ListRenderer.Rows`。
- `tree_list_renderer.xml`：`Rows`（分支）、`LeafRow`（记录行）两个模板。
  **父/子节点同一行模板**（原生 `RecordRow`），所有列信息一致。
- `tree_list.scss`：按深度给首列加缩进；父节点首列用 `::before` 画折叠箭头，
  箭头命中区以外的点击仍走原生行行为（打开表单）。

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
- 是父且已展开 → 继续下钻其 `group.list.records`；折叠则不再下钻。

`treeRows` 把这个自顶向下的遍历**扁平化成预序数组**（每项 `{record, group, depth}`），
模板只做一层 `t-foreach` 渲染兄弟行。**不要改回递归 `t-call`**：叶子行会挂载字段
组件（活动、头像、状态选择等），在高复杂度列表（如 project.task）里 Owl 对递归
`t-call` 树的块对账会静默失败——父分组点开后子行进不了 DOM，表现为"只能看到根、
点不开"。扁平化后与原生 list 的兄弟行结构一致，组件挂载正常。

因此无需 `id:array_agg` 额外读组，也无需服务端新方法；折叠与子记录懒加载全部复用
list 原生的 `Group.isFolded` / `Group.toggle()`。

### 行渲染与交互

- 父节点与叶子节点都用原生 `RecordRow` 渲染，列信息完全一致；父节点显示的是该
  记录自身的字段值（不使用 read_group 的聚合值）。
- 首列按 depth 缩进，叶子与同层父节点的文字对齐；父节点在缩进区用 `::before`
  画 `▸` / `▾`。
- 只有箭头命中区（按 depth 计算的水平区间）触发 `Group.toggle()`；首列其它区域
  和其它列保持原生行为（打开记录），即"点击不再作用于整行"。
- 折叠状态仍由 `Group.isFolded` 驱动，行 class 由 `getRowClass` 注入。

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
