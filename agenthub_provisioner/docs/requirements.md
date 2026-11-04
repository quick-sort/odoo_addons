# agenthub_provisioner — 业务需求与边界

## 背景

agenthub 把 agent-box 作为外部 agent 运行时。目标部署里有几十到上百个
agent-box 容器，每个容器都需要一组一致的配置：

- relay 地址、agent id、agent token、心跳间隔；
- LLM 接入点（网关地址、密钥、模型名）；
- 可选的 Odoo 接入信息（URL、数据库、登录、API key、Discuss channel）；
- 额外环境变量。

手工 `docker run` 无法保证幂等、无法审计、无法批量停启和排障，也无法在
agent-box 镜像升级后统一重建。本 addon 在 Odoo 里管理这些容器的生命周期。

**Odoo 仍然不在消息热路径。** provisioner 只做控制面操作（创建、启动、停止、
删除、查状态、看日志），消息投递仍由 relay 完成。

## 目标

1. **多宿主机**：在 Odoo 中注册一台或多台容器宿主机（`agenthub.provisioner.host`），
   每台宿主机通过可插拔 driver 控制。
2. **一 agent 一容器**：每个 `agenthub.agent` 最多绑定一个
   `agenthub.agent.deployment`；deployment 负责渲染环境变量和容器规格。
3. **配置集中**：LLM 接入点用可复用的 profile 表达；Odoo 接入信息与 relay
   连接信息按部署模式生成；其余配置通过 `extra_env` 追加。
4. **幂等**：重复 Apply 不重建容器；配置变化后重建；绝不接管不是本 addon
   创建的容器。
5. **两种控制方式**：本地/远程 Docker API（docker socket 或 TCP+TLS），以及
   SSH 到远端执行 `docker` 命令行。
6. **可审计、可异步**：所有变更记录时间、结果和错误；创建/重建通过
   `queue_job` 异步执行，不阻塞 Odoo worker。
7. **安全**：secret 只对系统管理员可见、不写日志；relay token 不在数据库
   存明文；镜像有白名单；容器必须带 managed label。

## 范围

### 在范围内

- 宿主机模型：driver 类型、连接参数、探测状态、默认镜像/网络/relay 地址/env。
- 部署模型：模式（relay / odoo_discuss）、镜像与拉取策略、容器名、环境变量、
  卷、网络、重启策略、期望状态与实际状态、配置 hash 与 drift 标记。
- LLM profile：base URL、认证方式与密钥、模型名映射。
- driver 抽象 component：`probe / apply / stop / remove / status / logs`。
- driver addon：
  - `agenthub_provisioner_docker`：Docker Engine API（unix socket / TCP+TLS）。
  - `agenthub_provisioner_ssh`：SSH + 远端 `docker` CLI。
- 部署动作：Apply、Stop、Remove、Rotate token、Sync、View logs。
- 定时 reconciliation：探测宿主机、同步容器状态、标记配置 drift。
- 管理 UI 与权限：仅系统管理员可操作宿主机与部署。

### 明确不做

- **不做编排平台**：不实现 Kubernetes / Swarm / Nomad 调度；它们将来以新
  driver addon 的形式接入。
- **不做零停机滚动升级**：同一 agent 重建期间允许短暂离线；relay 的
  redelivery 保证未完成 turn 不丢。
- **不做镜像构建**：只拉取/运行已有镜像。
- **不做任意远程命令执行**：SSH driver 只执行固定的 docker 子命令，不提供
  通用 exec 接口。
- **不做自动扩容/缩容**：容量与放置策略由管理员配置。
- **不替代 relay**：不参与消息路由、投递、presence 的实时计算；agent 在线
  状态仍以 relay 为准。
- **不自动轮换所有密钥**：只提供显式的 agent token 轮换；LLM/Odoo 密钥由
  管理员更新后 Apply。

## 非功能约束

- **规模**：单 Odoo 管理 100+ agent、多宿主机；控制面操作与消息吞吐解耦。
- **幂等**：driver 的 `apply` 必须可重复执行；同一配置 hash 不产生新容器。
- **安全边界**：
  - Docker socket 等价于宿主机 root；生产推荐 SSH driver，或至少使用
    TCP+TLS 且不暴露无认证端口。
  - SSH 默认严格校验 host key，私钥仅系统管理员可见。
  - relay token 由主密钥派生，数据库只存 hash；LLM/Odoo secret 明文仅存
    system-only 字段，UI 与日志打码。
  - 镜像必须匹配白名单；容器名与 env key 做正则校验。
- **可靠性**：动作失败必须落 `last_error`，不污染审计；重建先停旧容器，
  避免同一 agent 同时存在两条 relay 连接。
- **可观测**：宿主机探测状态、deployment 状态、最后一次动作/同步时间、
  drift 标记、driver 日志可查。
- **测试**：单元测试不连接真实 Docker/SSH；通过 fake client/transport 覆盖。

## 关键术语

- **host**：运行 agent-box 容器的宿主机；driver 的连接目标。
- **deployment**：一个 agent 在某个 host 上的容器声明。
- **driver**：把通用容器规格翻译成具体执行方式的 component。
- **spec**：与 driver 无关的容器规格（镜像、命令、env、卷、网络、label）。
- **drift**：容器实际 label 中的 config hash 与当前渲染结果不一致。
- **managed container**：带 `agenthub.managed=true` label 的容器；只有这类
  容器允许被本 addon 停止或删除。
