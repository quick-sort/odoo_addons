# agenthub_provisioner — 系统设计

## 1. 定位

`agenthub_provisioner` 是 agenthub 家族的**控制面** addon：它把
`agenthub.agent` 声明的一个 agent-box 实例落成宿主机上的一个容器，并负责
后续的启动、停止、删除、状态同步和日志查看。

它不参与消息路径：

- 消息仍然经 relay 投递；
- agent 是否在线以 relay presence 为准；
- 容器 `running` 不等于 agent `online`，UI 必须同时展示两者。

```
Odoo（配置 / UI / 审计）
   │  Apply / Stop / Remove
   ▼
agenthub.provisioner.host ── driver component ──► Docker Engine
   │                                   ├─ unix socket / TCP+TLS
   │                                   └─ SSH → 远端 docker CLI
   ▼
agent-box container ── WebSocket ──► relay ◄── 用户消息
```

## 2. Addon 分层

| addon | 内容 | 依赖 |
|---|---|---|
| `agenthub_provisioner` | 模型、抽象 driver、env 渲染、状态机、UI、cron | `agenthub`, `component`, `queue_job` |
| `agenthub_provisioner_docker` | `driver_type=docker` 的字段与 component | core + Python `docker` |
| `agenthub_provisioner_ssh` | `driver_type=ssh` 的字段与 component | core + Python `paramiko` |

core 不 import `docker`、`paramiko` 或 `llm`；`driver_type` 在 core 里是
`selection=[]`，由 driver addon 通过 `selection_add` 追加，和
`agenthub.channel.channel_type` / `agenthub.agent.agent_type` 完全同构。

## 3. 数据模型

### 3.1 `agenthub.provisioner.host`

继承 `collection.base`，作为 driver component 的 collection。

| 字段 | 类型 | 说明 |
|---|---|---|
| `name` | Char, required | 宿主机名称 |
| `driver_type` | Selection(selection=[]), required | core 置空；driver addon 追加 |
| `active` | Boolean | 停用后不再探测/同步 |
| `state` | Selection(unknown/online/offline/error) | 最近一次探测结果 |
| `last_probe_at` | Datetime | 最近探测时间 |
| `last_error` | Text | 最近错误（已打码） |
| `default_image` | Char | 部署未填镜像时使用 |
| `default_network` | Char | 加入的 Docker network |
| `default_relay_url` | Char | 部署未填 relay 地址时使用 |
| `default_env` | Json | 宿主机级默认环境变量 |
| `deployment_ids` | One2many | 该宿主机上的部署 |

driver 专属字段由 driver addon `_inherit` 追加，core 不感知。

### 3.2 `agenthub.provisioner.llm`

可复用的 LLM 接入点，避免每个 deployment 重复填密钥。

| 字段 | 类型 | 说明 |
|---|---|---|
| `name` | Char, required | profile 名称 |
| `base_url` | Char | → `ANTHROPIC_BASE_URL` |
| `auth_mode` | Selection(api_key/auth_token) | 决定用 `ANTHROPIC_API_KEY` 还是 `ANTHROPIC_AUTH_TOKEN` |
| `secret` | Char, groups=base.group_system | API key / auth token |
| `router_model` | Char | → `ANTHROPIC_SMALL_FAST_MODEL` |
| `haiku_model` | Char | → `ANTHROPIC_DEFAULT_HAIKU_MODEL` |
| `sonnet_model` | Char | → `ANTHROPIC_DEFAULT_SONNET_MODEL` |
| `opus_model` | Char | → `ANTHROPIC_DEFAULT_OPUS_MODEL` |
| `extra_env` | Json | profile 级额外 env |
| `active` | Boolean | |

校验：`router_model` 与 `haiku_model` 至少填一个（agent-box 启动需要路由模型）。
`secret` 允许为空，以支持无鉴权的内网网关。

### 3.3 `agenthub.agent.deployment`

一个 agent 最多一个 deployment；继承 `mail.thread` 记录状态变更。

| 分组 | 字段 | 说明 |
|---|---|---|
| 关联 | `name` | 显示名 |
| | `agent_id` | Many2one `agenthub.agent`，required，unique |
| | `host_id` | Many2one host，required |
| 运行 | `mode` | relay / odoo_discuss |
| | `image` | 镜像引用 |
| | `pull_policy` | missing / always / never |
| | `command` | Json 字符串数组；默认按 mode 生成 |
| | `container_name` | 唯一，默认 `agenthub-agent-<agent_id>` |
| | `runtime_id` | 远端容器 id，只读 |
| 状态 | `desired_state` | running / stopped / absent，默认 stopped |
| | `state` | draft / provisioning / running / stopping / stopped / error / removed |
| | `config_hash` | 最近一次 Apply 的规格 hash |
| | `config_drift` | 容器 label 中的 hash 与当前渲染不一致 |
| | `last_action_at` | 最近动作时间 |
| | `last_status_at` | 最近状态同步时间 |
| | `last_error` | 最近错误（已打码） |
| relay | `relay_url` | 为空时用 host 默认值 |
| | `relay_heartbeat_seconds` | 默认 20 |
| llm | `llm_profile_id` | Many2one `agenthub.provisioner.llm` |
| odoo | `odoo_url` / `odoo_db` / `odoo_login` | odoo_discuss 模式使用 |
| | `odoo_api_key` | groups=base.group_system |
| | `odoo_channel_id` | Integer |
| 其它 | `extra_env` | Json |
| | `volumes` | Json；默认命名卷 |
| | `network` | 为空时用 host 默认值 |
| | `restart_policy` | no / always / unless-stopped / on-failure |
| | `auto_heal` | 默认 False；见 6.3 |
| | `logs_tail` | 默认 200 |

约束：

- `UNIQUE(agent_id)`、`UNIQUE(container_name)`。
- `mode=relay` 时 `relay_url`（或 host 默认）必填。
- `mode=odoo_discuss` 时 `odoo_url`/`odoo_db`/`odoo_login`/`odoo_api_key` 必填。
- `container_name` 匹配 `^[A-Za-z0-9][A-Za-z0-9_.-]{1,62}$`。
- `extra_env` 的 key 匹配 `^[A-Z_][A-Z0-9_]*$`，value 不含换行/NUL。
- `extra_env` 不得包含 `RELAY_AGENT_ID`、`RELAY_AGENT_TOKEN`（这两个由系统生成）。

### 3.4 `agenthub.agent` 扩展

provisioner 向 core 的 agent 追加：

- `provisioner_token_version`：Integer，默认 1，groups=base.group_system；
- `deployment_ids`：One2many；
- `_provisioner_token()`：按主密钥派生明文 token（见 5.2）。

不修改 core 的 `token_hash` 语义；只在 Apply/轮换时写入它的值。

## 4. Driver component 接口

### 4.1 契约对象

```python
# contract.py
from dataclasses import dataclass
from typing import Mapping


@dataclass(frozen=True)
class ContainerSpec:
    name: str
    image: str
    command: tuple[str, ...]
    env: Mapping[str, str]
    volumes: Mapping[str, Mapping[str, str]]
    labels: Mapping[str, str]
    config_hash: str
    network: str | None = None
    restart_policy: str = "unless-stopped"
    pull_policy: str = "missing"


@dataclass(frozen=True)
class ContainerState:
    id: str | None
    name: str
    status: str          # missing | created | running | exited | dead | ...
    image: str | None = None
    health: str | None = None
    labels: Mapping[str, str] | None = None   # used for config-drift detection
    error: str | None = None


@dataclass(frozen=True)
class HostProbe:
    ok: bool
    version: str | None = None
    detail: str | None = None


class ProvisionerError(Exception):
    """Driver boundary error; ``code`` is stable, ``detail`` is user-facing."""

    def __init__(self, code, detail):
        super().__init__(detail)
        self.code = code
        self.detail = detail
```

### 4.2 抽象 component

```python
# components/driver.py
from odoo.addons.component.core import AbstractComponent


class AgenthubProvisionerDriver(AbstractComponent):
    _name = "agenthub.provisioner.driver"
    _collection = "agenthub.provisioner.host"

    def probe(self, host) -> HostProbe:
        """Check connectivity and return the engine version."""

    def apply(self, host, spec: ContainerSpec) -> ContainerState:
        """Idempotently ensure a container matches ``spec`` and is running."""

    def stop(self, host, container_id: str, timeout: int = 10) -> None:
        """Stop a managed container. No-op when already stopped/missing."""

    def remove(self, host, container_id: str) -> None:
        """Stop and delete a managed container. No-op when missing."""

    def status(self, host, container_id: str) -> ContainerState:
        """Return the current container state; ``missing`` when absent."""

    def logs(self, host, container_id: str, tail: int = 200) -> str:
        """Return the last ``tail`` log lines."""
```

### 4.3 解析

和 core 现有扩展点一致：

```python
class AgenthubProvisionerHost(models.Model):
    _name = "agenthub.provisioner.host"
    _inherit = ["collection.base"]

    driver_type = fields.Selection(selection=[], required=True)

    def _driver(self):
        with self.work_on(self._name) as work:
            return work.component(usage=self.driver_type)
```

driver addon 只做三件事：

```python
class AgenthubProvisionerHost(models.Model):
    _inherit = "agenthub.provisioner.host"
    driver_type = fields.Selection(selection_add=[("ssh", "SSH")])
    ssh_host = fields.Char(...)


class AgenthubProvisionerDriverSsh(Component):
    _name = "agenthub.provisioner.driver.ssh"
    _inherit = "agenthub.provisioner.driver"
    _usage = "ssh"
```

### 4.4 `apply()` 语义（所有 driver 必须一致）

1. 按 `spec.name` 查找；同时核对 label `agenthub.deployment_id`。
2. 不存在 → 按 `pull_policy` 拉镜像，创建并启动。
3. 存在、`agenthub.managed=true`、label 中的 `agenthub.config_hash` 与
   `spec.config_hash` 相同、镜像相同 → 确保 running，不重建。
4. 存在但 hash 或镜像不同 → **先 stop 旧容器，再 remove，再创建新容器**。
   不能先建后停：relay 允许同一 agent 有多条 WebSocket，双开会把 turn
   拆到两个容器。
5. 同名容器缺少 `agenthub.managed=true`，或 label 的 deployment id 不是当前
   记录 → 抛 `ProvisionerError("CONFLICT", ...)`，绝不接管。
6. `pull_policy=never` 且镜像不存在 → `IMAGE_MISSING`；拉取失败 → `PULL_FAILED`。

### 4.5 容器 spec

`deployment._render_spec()` 生成：

```python
ContainerSpec(
    name=self.container_name,
    image=self.image,
    command=tuple(self.command or self._default_command()),
    env=self._render_env(),
    volumes=self._render_volumes(),
    labels={
        "agenthub.managed": "true",
        "agenthub.agent_id": str(self.agent_id.id),
        "agenthub.deployment_id": str(self.id),
        "agenthub.config_hash": config_hash,
    },
    config_hash=config_hash,
    network=self.network or self.host_id.default_network or None,
    restart_policy=self.restart_policy,
    pull_policy=self.pull_policy,
)
```

默认卷：

```json
{"<container_name>-home": {"bind": "/home/agent", "mode": "rw"}}
```

agent-box 的配置、项目、Claude 会话和 skills 都在 `/home/agent` 下；需要把
项目放到 `/app/data` 时由管理员在 `volumes` 中追加。

默认命令：

- `mode=relay` → `["uv", "run", "agent-box", "--relay"]`
- `mode=odoo_discuss` → `["uv", "run", "agent-box", "--odoo"]`

## 5. 环境变量

### 5.1 优先级

从低到高：

```
host.default_env
  < relay / odoo 派生值
  < llm_profile._render_env()
  < deployment.extra_env
```

`extra_env` 可以覆盖普通 key，但不得覆盖 `RELAY_AGENT_ID` 和
`RELAY_AGENT_TOKEN`。所有 key/value 在写入时校验；value 含换行或 NUL 直接
拒绝（防止 env-file 注入）。

### 5.2 relay token 派生

不在数据库保存每个 agent 的明文 token：

```python
secret = os.environ.get("AGENTHUB_PROVISIONER_TOKEN_SECRET") \
    or ir.config_parameter("agenthub.provisioner.token_secret")
token = base64url(HMAC-SHA256(
    secret, f"agenthub.agent:{agent.id}:{agent.provisioner_token_version}"
))
agent.token_hash = sha256(token)
```

- 主密钥优先从环境变量读取（可用 `server_environment` 注入），其次读
  `ir.config_parameter`；两者都没有时 Apply 报错并提示配置。
- Apply 时把派生的 token 写入 `agenthub.agent.token_hash`，relay 下一次
  配置同步后生效。
- `action_rotate_token()` 增加 `provisioner_token_version`，写新的 hash，
  然后重建容器。旧容器在下一次连接时会被 relay 拒绝，因此轮换与重建必须
  在同一动作里完成。
- 明文只存在于渲染后的 spec 和容器 env 中，不写日志、不存 Odoo 字段。

### 5.3 LLM profile 渲染

| profile 字段 | 环境变量 |
|---|---|
| `base_url` | `ANTHROPIC_BASE_URL` |
| `secret` + `auth_mode=api_key` | `ANTHROPIC_API_KEY` |
| `secret` + `auth_mode=auth_token` | `ANTHROPIC_AUTH_TOKEN` |
| `router_model` | `ANTHROPIC_SMALL_FAST_MODEL` |
| `haiku_model` | `ANTHROPIC_DEFAULT_HAIKU_MODEL` |
| `sonnet_model` | `ANTHROPIC_DEFAULT_SONNET_MODEL` |
| `opus_model` | `ANTHROPIC_DEFAULT_OPUS_MODEL` |
| `extra_env` | 原样追加 |

### 5.4 Odoo 接入信息

`mode=odoo_discuss` 时：

| 字段 | 环境变量 |
|---|---|
| `odoo_url` | `ODOO_URL` |
| `odoo_db` | `ODOO_DB` |
| `odoo_login` | `ODOO_LOGIN` |
| `odoo_api_key` | `ODOO_API_KEY` |
| `odoo_channel_id` | `ODOO_CHANNEL_ID`（有值时） |

`mode=relay` 不渲染这些值。

### 5.5 打码与 hash

- `_render_env_preview()` 把 key 含 `KEY` / `TOKEN` / `SECRET` / `PASSWORD`
  的值替换为 `***`，供 UI 和日志使用。
- `config_hash = sha256(json.dumps({image, command, env, volumes, network,
  restart_policy}, sort_keys=True))`。只存 hash；不存完整 env。
- 写 `last_error` 前，把已知 secret 值替换为 `***`。

## 6. 生命周期

### 6.1 状态

`desired_state` 表达意图：`running` / `stopped` / `absent`。
`state` 表达最近一次动作/同步的结果：

```
draft ──Apply──► provisioning ──成功──► running
  ▲                    │失败              │Stop
  │                    ▼                 ▼
  └──── Remove ──── error ◄────── stopping ──► stopped
                       │                          │
                       └────── Apply ◄────────────┘
```

`removed` 表示容器已删除，记录保留以便重新 Apply。

### 6.2 动作

| 动作 | desired_state | 状态迁移 | 执行 |
|---|---|---|---|
| Apply | running | → provisioning | `queue_job` |
| Stop | stopped | → stopping | `queue_job` |
| Remove | absent | → stopping | `queue_job` |
| Sync | 不变 | 按 driver 结果 | 同步 |
| Rotate token | running | → provisioning | 先 bump version，再 `queue_job` |
| View logs | 不变 | 不变 | 同步读 `logs()` |

job 使用 `identity_key=f"agenthub_provisioner.deployment.{id}"`，channel 为
`root.agenthub`；需要在 `odoo.conf` 的 `[queue_job] channels` 中加入容量，
例如 `root.agenthub:2`。job 内部捕获 driver 异常并写 `last_error`，不让
queue_job 无限重试。

### 6.3 定时 reconciliation

`ir.cron` 每 2 分钟执行 `agenthub.agent.deployment._cron_reconcile()`：

1. 对每个 active host 调 `probe()`，失败只更新 host 状态，不把其上的部署
   批量标错。
2. 对每个非 draft/removed 的 deployment 调 `status()`，更新
   `runtime_id`、`state`、`last_status_at`。
3. 比较容器 label 的 `agenthub.config_hash` 与当前 `_spec_hash()`：
   - 不一致 → `config_drift=True`，**不自动重建**；
   - 一致 → `config_drift=False`。
4. `auto_heal=True` 且 `desired_state=running` 且容器缺失/退出 → 触发 Apply；
   默认关闭，避免故障循环。
5. 状态为 `provisioning` / `stopping` 的记录跳过，避免与在途 job 冲突。

## 7. 安全

- **权限**：host、llm profile、deployment 仅 `base.group_system` 可读写；
  secret 字段额外 `groups="base.group_system"`。不向 `base.group_user` 开放。
- **镜像白名单**：`ir.config_parameter` 的
  `agenthub.provisioner.allowed_images`，逗号分隔 glob，默认
  `ghcr.io/quick-sort/agent-box:*`。不匹配时拒绝 Apply。
- **容器名**：正则校验；所有 label 由服务端生成。
- **unmanaged 容器**：没有 `agenthub.managed=true` 的同名容器一律拒绝操作。
- **Docker socket**：等价 root。生产优先 SSH driver；TCP 端点必须 TLS，
  禁止非 loopback 的明文 TCP。
- **SSH**：默认严格 host key 校验；私钥 system-only；只执行固定 docker
  子命令。
- **日志**：driver 返回的错误在写入前打码；不记录完整 env。

## 8. UI

- 菜单 `Agent Hub → Provisioning`：
  - `Hosts`：list/form，显示 driver、state、last probe、默认值。
  - `Deployments`：list/form，statusbar，Apply/Stop/Remove/Sync/Rotate/Logs。
  - `LLM Profiles`：list/form。
- `agenthub.agent` 表单加 smart button，显示 deployment 数量与状态。
- deployment 表单分 tab：Relay、LLM、Odoo、Environment、Advanced。

## 9. 测试策略

- 不连接真实 Docker/SSH；core 用 stub driver（`TransactionComponentRegistryCase`
  注册测试 component，或 patch `host._driver`）。
- env：优先级、保留 key、换行拒绝、打码、hash 稳定性。
- 状态机：Apply/Stop/Remove 成功与失败、drift 检测、cron 跳过在途状态。
- token：派生稳定性、version 变化、hash 同步。
- 安全：非 system 用户拒绝、白名单、unmanaged 容器冲突。
- driver addon：fake docker client / fake paramiko transport；断言命令参数、
  env 文件生命周期、错误映射，不发起网络请求。

## 10. 扩展点与后续

- 新 driver：新增独立 addon，`selection_add` + 一个 component，不改 core。
- 可选 `agenthub_provisioner_llm`：把 `llm.provider` 映射成 LLM profile，
  core 不依赖 `llm`。
- 后续：滚动升级、registry 凭据、资源限制（cpu/mem）、多 host 放置策略、
  外部 secret manager。

## 11. 被否决的方案

| 方案 | 否决理由 |
|---|---|
| core 里按 `driver_type` 写 if/else | 违背仓库 provider 分层规范；依赖和分支堆在一个 addon。 |
| 只支持单个 addon、同时依赖 docker 和 paramiko | 不需要其中一种驱动的部署被迫安装另一个依赖。 |
| SSH 端口转发 Docker socket 后复用 SDK | 需要 streamlocal 转发或远端 TCP，复杂度和暴露面更高。 |
| Odoo 直接 subprocess 调 `ssh`/`docker` | Odoo 镜像没有这些 CLI；拼 shell 字符串有注入风险。 |
| 在 deployment 存 relay token 明文 | 违背 core “只存 token_hash”的边界；改用主密钥派生。 |
| 每次 cron 都重建容器 | 反复打断正在执行的 turn；改为 drift 标记 + 显式 Apply。 |
| 自动接管同名容器 | 可能误删用户自己的容器；只操作带 managed label 的容器。 |
| 把 agent-box 跑在 Odoo 容器内 | 失去隔离，违背“Odoo 不在热路径”。 |
