# agenthub_provisioner_docker — 系统设计

## 1. 扩展点

本 addon 依赖 `agenthub_provisioner`，只做两件事：

1. 给 `agenthub.provisioner.host` 追加 `driver_type=docker` 与连接字段；
2. 注册 `agenthub.provisioner.driver.docker` component。

```python
class AgenthubProvisionerHost(models.Model):
    _inherit = "agenthub.provisioner.host"

    driver_type = fields.Selection(
        selection_add=[("docker", "Docker")],
        ondelete={"docker": "cascade"},
    )
    # Not ``required``: the same host model is shared with other drivers.
    # The driver validates the endpoint when it is used.
    docker_url = fields.Char(default="unix:///var/run/docker.sock")
    docker_timeout = fields.Integer(default=30)
    docker_tls = fields.Boolean()
    docker_tls_ca = fields.Char()
    docker_tls_cert = fields.Char()
    docker_tls_key = fields.Char()


class AgenthubProvisionerDriverDocker(Component):
    _name = "agenthub.provisioner.driver.docker"
    _inherit = "agenthub.provisioner.driver"
    _usage = "docker"
```

## 2. 客户端

```python
docker.DockerClient(
    base_url=host.docker_url,
    timeout=host.docker_timeout,
    tls=docker.tls.TLSConfig(
        ca_cert=host.docker_tls_ca,
        client_cert=(host.docker_tls_cert, host.docker_tls_key),
        verify=True,
    ) if host.docker_tls else None,
)
```

校验：

- scheme 只允许 `unix` / `tcp`；
- `tcp://` 且非 loopback 时必须 `docker_tls=True`；
- TLS 文件路径必须存在于 Odoo 容器内（挂载提供）。

## 3. 方法映射

| 契约 | Docker SDK |
|---|---|
| `probe` | `client.ping()` + `client.version()["Version"]` |
| `status` | `client.containers.get(id)` → `.status` / `.image.tags` / `.attrs["State"]` |
| `stop` | `container.stop(timeout=...)`，`NotFound` 视为 no-op |
| `remove` | `container.remove(force=True)`，`NotFound` 视为 no-op |
| `logs` | `container.logs(tail=tail, timestamps=True).decode(...)` |
| `apply` | 查找 → 比较 label → 拉取 → 创建/启动/重建 |

### apply 流程

1. `_find(spec.name)`；找不到按名字再查。
2. 找到时校验 label：
   - 无 `agenthub.managed=true` → `CONFLICT`；
   - `agenthub.deployment_id` 不符 → `CONFLICT`。
3. hash 与镜像都相同 → `container.start()`（若已停止）并返回状态。
4. 否则 `stop` + `remove`，然后创建。
5. 镜像：`pull_policy=always` 直接 pull；`missing` 在本地不存在时 pull；
   `never` 且不存在 → `IMAGE_MISSING`。
6. 创建参数：
   - `name`、`image`、`command`、`environment`、`labels`；
   - `volumes`（Docker SDK 的 `{name: {"bind": path, "mode": mode}}`）；
   - `network`、`restart_policy`；
   - `detach=True`，随后 `start()`。

## 4. 错误映射

| 场景 | code |
|---|---|
| 连接失败 / ping 失败 | `UNREACHABLE` |
| 同名未托管容器 | `CONFLICT` |
| 镜像缺失且禁止拉取 | `IMAGE_MISSING` |
| 拉取失败 | `PULL_FAILED` |
| 创建/启动失败 | `CREATE_FAILED` / `START_FAILED` |
| 其它 SDK 异常 | `DOCKER_ERROR` |

## 5. 测试

- 注入 fake `DockerClient`（patch `_client`），断言：
  - probe 成功/失败；
  - apply 创建参数、label、env、volumes、network；
  - 相同 hash 不 remove/create；
  - 不同 hash 的调用顺序为 stop → remove → create → start；
  - 未托管同名容器抛 `CONFLICT`；
  - TCP 非 loopback 无 TLS 被拒绝。
- 不连接真实 socket，不拉取镜像。

## 6. 被否决的方案

| 方案 | 原因 |
|---|---|
| subprocess 调 `docker` CLI | Odoo 镜像没有 CLI，且需要挂 socket 才能用；SDK 更直接。 |
| 把 docker 依赖放进 core | 不需要该驱动的部署被迫安装 SDK。 |
| 自动接管同名容器 | 可能删除用户容器。 |
| 非 TLS 的 TCP 端点 | Docker API 等价 root，明文暴露不可接受。 |
