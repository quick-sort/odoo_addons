# web_dag — 开发约束（自动加载）

设计文档见 `docs/`，这是唯一要求来源，改代码前先读：

- `docs/requirements.md` — 业务需求与边界
- `docs/design.md` — 架构、数据契约、被否决的方案
- `docs/acceptance.md` — 验收标准（QC 唯一依据）

红线（来自 design.md，勿违背）：
1. 数据契约固定为 `get_dag_data(domain)` 返回 `{nodes:[{id,name,state}], edges:[{source,target}]}`，`state ∈ {done,canceled,open}`。
2. 前端不读宿主模型字段：只认 `id/name/state` 与 `source/target`，不 import 业务模型。
