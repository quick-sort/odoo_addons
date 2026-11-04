# agenthub_provisioner_docker — 开发约束（自动加载）

设计文档见 `docs/`，这是唯一要求来源，改代码前先读：

- `docs/requirements.md`
- `docs/design.md`
- `docs/acceptance.md`

红线（来自 design.md，勿违背）：

1. 只实现 Docker driver contract；不把 docker 依赖或分支放进 core。
2. 只操作带 `agenthub.managed=true` label 的容器；同名未托管容器报冲突，
   不 stop、不 remove。
3. 配置变化重建时必须先 stop/remove 旧容器，再 create/start，避免同一
   agent 双连接。
4. 非 loopback 的 `tcp://` 端点必须 TLS；拒绝明文。
5. 测试只用 fake Docker client，不连接真实 socket、不拉镜像。
