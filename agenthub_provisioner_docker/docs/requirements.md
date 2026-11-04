# agenthub_provisioner_docker — 业务需求与边界

## 背景

`agenthub_provisioner` 定义了容器生命周期和 driver component 契约。本 addon
提供第一种实现：直接调用 Docker Engine API，适用于 Odoo 与 Docker 守护进程
同机（unix socket）或通过网络访问（TCP+TLS）的场景。

## 目标

1. 支持 `unix://` socket 和 `tcp://` API；TCP 必须可选 TLS。
2. 实现 core 契约：`probe / apply / stop / remove / status / logs`。
3. `apply` 严格幂等：相同配置 hash 不重建；配置变化时先停旧容器再建新容器。
4. 只操作带 `agenthub.managed=true` label 的容器；同名未托管容器报冲突。
5. 连接失败、镜像拉取失败、创建失败等都映射为 `ProvisionerError`，由 core
   写入 `last_error`。

## 范围

### 在范围内

- `driver_type=docker` 的宿主机字段与 component。
- Docker SDK 客户端构造：socket / TCP / TLS、超时。
- 镜像拉取策略、容器创建、启动、停止、删除、状态、日志。
- fake client 单元测试。

### 明确不做

- Swarm、Kubernetes、Podman 等其它运行时。
- 镜像构建、registry 登录管理（使用宿主机已有的 Docker 凭据）。
- 容器内任意命令执行。
- 资源配额、调度/放置策略。

## 非功能约束

- 不记录完整环境变量；错误信息打码由 core 统一处理。
- TCP 端点禁止非 loopback 明文；必须 TLS。
- 测试不连接真实 Docker socket、不发网络请求。
