# Tree List View — 验收标准

QC 依据。前端渲染行为由 `web_tree_list_demo`（装 demo 数据 + 浏览器操作）验证；
Python 侧由 `tests/test_view.py` 锁定 `js_class="tree_list"` 的 arch 可被接受。

## 功能点

1. **视图注册**：`views` registry 存在 `tree_list`，`<list js_class="tree_list">`
   的 arch 通过后端校验（RNG + `_validate_tag_list` 不报错）。
   - 验收：`tests/test_view.py::test_list_view_accepts_tree_list_js_class` 通过。

2. **自动检测**：单个自引用 `many2one` groupBy（`field.relation === resModel`）触发
   tree 模式；非自引用或非单字段 groupBy 不触发。
   - 验收：demo 模块装好后，菜单"Tree List Demo"默认 `default_group_by="parent_id"`
     直接呈现 tree；手动切到其它分组字段或不分组时回退为普通 list。

3. **多级折叠与缩进**：所有节点按父树深度缩进，可逐级展开/折叠，≥3 层可见
   （根→子→孙）；同一层级的叶子与父节点首列文字对齐。
   - 验收：demo 数据（Root A → A-Child 1 → Grandchild 1/2 等）在浏览器中呈现
     多级缩进；点击父节点首列的小箭头（▸/▾）逐级展开/折叠。
   - **仅箭头可点**：点击首列的其它区域或其它列不折叠，仍按原生行为打开该记录
     的 form。
   - 复杂列表回归：在含活动/头像/状态选择等字段组件的列表（如 `project.task`
     按 Parent Task 分组）中，父分组点开后子行必须实际进入 DOM；不得出现"分组
     状态已展开（`isFolded=false`、子记录已加载）但表格仍只有根行"——这是 Owl
     对递归 `t-call` 树做块对账时的静默失败，渲染必须走扁平兄弟行。

4. **统一行渲染**：父节点与叶子节点都复用原生 `web.ListRenderer.RecordRow`，
   显示相同的字段/widget/按钮组列（父节点显示自身记录的字段值），行与表头等宽；
   tree 模式不显示记录选择列（只读契约）；点击单元格与普通 list 一致打开对应
   记录的 form（箭头命中区除外）。
   - 验收：demo 中父节点与叶子行都有 name 列（description optional 列可显示），
     行右端与表头对齐；点击非箭头区域进入该记录的 form 视图。

5. **非 tree 回退**：不按自引用字段分组时，行为与原生 list 一致（编辑/排序/其它
   分组照常）。
   - 验收：demo 视图去掉 parent_id 分组后仍可正常展示、排序。

## 已知局限（v1，非 QC 阻塞）

- tree 模式只读（无 edit toggle）、多字段 groupBy 叠加不递归、不拖拽 reparent。
