# agenthub_provisioner — 开发约束（自动加载）

设计文档见 `docs/`，这是唯一要求来源，改代码前先读：

- `docs/requirements.md` — 业务需求与边界
- `docs/design.md` — 模型、component 接口、状态机、被否决方案
- `docs/acceptance.md` — 验收标准（QC 唯一依据）

红线（来自 design.md，勿违背）：

1. **core 只放抽象**：不 import `docker`、`paramiko`、`llm`；`driver_type`
   保持 `selection=[]`，具体 driver 只加独立 addon。
2. **控制面，不是消息路径**：provisioner 不参与 relay 路由/投递；容器
   `running` 不等于 agent `online`。
3. **只操作 managed 容器**：没有 `agenthub.managed=true` label 的同名容器
   一律拒绝，绝不接管或删除。
4. **先停后建**：配置变化重建时先 stop/remove 旧容器，避免同一 agent 同时
   存在两条 relay 连接。
5. **relay token 不落明文**：由主密钥派生，数据库只写 `token_hash`；日志和
   UI 打码。
6. **动作仅系统管理员可执行**；镜像必须匹配白名单。
