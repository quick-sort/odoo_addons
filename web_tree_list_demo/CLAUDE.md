# web_tree_list_demo — 开发约束（自动加载）

设计文档见 `docs/`，这是唯一要求来源，改代码前先读：

- `docs/requirements.md` — 业务需求与边界
- `docs/design.md` — 模型、视图、demo 数据
- `docs/acceptance.md` — 验收标准（QC 唯一依据）

红线（来自 design.md，勿违背）：

1. 本模块只做 `web_tree_list` 的演示/验证，不承载业务逻辑。
2. demo 数据只能放 `demo/`，不得混入 `data/`（生产环境不加载）。
