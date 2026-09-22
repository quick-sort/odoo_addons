# wecom_hr — 开发约束（自动加载）

设计文档见 `docs/`，这是唯一要求来源，改代码前先读：

- `docs/requirements.md` — 业务需求与边界（做/不做）
- `docs/design.md` — 架构、字段映射、同步算法、被否决的方案
- `docs/acceptance.md` — 验收标准（QC 唯一依据）

红线（来自 design.md，勿违背）：

1. 映射层 `sync_to_hr()` 只吃 `wecom.*` 缓存记录、**不联网**；网络只在 `wecom.app.sync_hr()` 编排层。
2. 同步**单向且幂等**：按 `wecom_userid` / `wecom_id` 匹配，重复执行不重复建；不在企微的员工保留不动。
3. 不新建业务模型，只在既有模型上 `_inherit` 加字段与方法。
