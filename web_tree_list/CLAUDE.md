# web_tree_list — 开发约束（自动加载）

设计文档见 `docs/`，这是唯一要求来源，改代码前先读：

- `docs/requirements.md` — 业务需求与边界
- `docs/design.md` — 架构、树重建机制、被否决方案
- `docs/acceptance.md` — 验收标准（QC 唯一依据）

红线（来自 design.md，勿违背）：

1. tree 模式只能由"单个自引用 `many2one` groupBy"触发；非 tree 分支必须原样回退到
   `web.ListRenderer.Rows`，不得改变原生 list 行为。
2. 树重建必须复用 `RelationalModel` 的扁平分组结果，不得额外发 `id:array_agg` 或
   新增后端方法。
3. 折叠/子记录懒加载必须走 `Group.isFolded` / `Group.toggle()`，不得自造第二套
   折叠状态。
