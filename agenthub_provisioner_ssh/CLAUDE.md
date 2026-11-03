# agenthub_provisioner_ssh — 开发约束（自动加载）

设计文档见 `docs/`，这是唯一要求来源，改代码前先读：

- `docs/requirements.md`
- `docs/design.md`
- `docs/acceptance.md`

红线（来自 design.md，勿违背）：

1. 只实现 SSH driver contract；不把 paramiko 依赖或分支放进 core。
2. 默认严格校验 host key；关闭必须显式配置。
3. env 不进入命令行参数：经 stdin 写远端 0600 临时文件，成功/失败都清理。
4. 所有命令参数来自 argv 列表并 `shlex.quote`；不拼接未转义输入。
5. 只操作带 `agenthub.managed=true` label 的容器；同名未托管容器报冲突。
6. 测试使用 fake transport，不建立真实 SSH 连接。
