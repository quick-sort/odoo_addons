# agenthub_provisioner_ssh — 业务需求与边界

## 背景

很多生产主机不把 Docker socket 暴露给 Odoo 容器（socket 等价于宿主机 root）。
本 addon 提供第二种 driver：通过 SSH 登录远端主机，在远端执行 `docker`
命令行。Odoo 容器不需要安装 docker 或 ssh 客户端，只需 Python `paramiko`。

## 目标

1. 实现 core 的 `probe / apply / stop / remove / status / logs` 契约。
2. 支持密码之外的私钥认证；默认严格校验 host key。
3. 环境变量不进入命令行参数（避免被 `ps` 看到）：经 stdin 写入远端 0600
   临时文件，用 `docker --env-file` 读取，并保证成功/失败都清理。
4. 所有命令参数用安全的 shell quoting；容器名/label 只使用服务端生成的值。
5. 错误映射为 `ProvisionerError`，由 core 记录。

## 范围

### 在范围内

- `driver_type=ssh` 的宿主机字段与 component。
- paramiko 连接、host key 校验、私钥认证、命令超时。
- 远端 `docker` CLI 的 inspect / pull / create / start / stop / rm / logs。
- 远端 env 临时文件的写入与清理。
- fake transport 单元测试。

### 明确不做

- 通用远程命令执行或交互式 shell。
- SSH agent forwarding、跳板机链、ProxyCommand。
- 远端 docker 安装/配置管理。
- 非 Docker 的容器运行时。

## 非功能约束

- 默认 `ssh_strict_host_key=True`；关闭需要显式配置。
- 私钥仅 `base.group_system` 可见。
- 不记录 env 内容到日志；错误信息由 core 打码。
- 测试不使用真实 SSH/网络。
