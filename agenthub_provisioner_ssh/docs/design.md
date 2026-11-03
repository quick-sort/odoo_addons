# agenthub_provisioner_ssh — 系统设计

## 1. 扩展点

```python
class AgenthubProvisionerHost(models.Model):
    _inherit = "agenthub.provisioner.host"

    driver_type = fields.Selection(
        selection_add=[("ssh", "SSH")],
        ondelete={"ssh": "cascade"},
    )
    # Not ``required``: the same host model is shared with other drivers.
    # ``_validate_host`` rejects missing values when the driver is used.
    ssh_host = fields.Char()
    ssh_port = fields.Integer(default=22)
    ssh_user = fields.Char()
    ssh_private_key = fields.Text(groups="base.group_system")
    ssh_key_passphrase = fields.Char(groups="base.group_system")
    ssh_known_hosts = fields.Text()
    ssh_strict_host_key = fields.Boolean(default=True)
    ssh_timeout = fields.Integer(default=15)
    remote_docker = fields.Char(default="docker")


class AgenthubProvisionerDriverSsh(Component):
    _name = "agenthub.provisioner.driver.ssh"
    _inherit = "agenthub.provisioner.driver"
    _usage = "ssh"
```

## 2. 连接

```python
client = paramiko.SSHClient()
if host.ssh_strict_host_key:
    if host.ssh_known_hosts:
        client.load_system_host_keys()  # 或写入临时 known_hosts
        client.get_host_keys().add(...)
    else:
        client.load_system_host_keys()
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
else:
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
client.connect(
    hostname=host.ssh_host,
    port=host.ssh_port,
    username=host.ssh_user,
    pkey=parse_private_key(host.ssh_private_key, passphrase),
    timeout=host.ssh_timeout,
    allow_agent=False,
    look_for_keys=False,
)
```

- 私钥支持 RSA/ECDSA/Ed25519，使用 `paramiko.PKey.from_private_key` 系列。
- 默认 `RejectPolicy`；`ssh_known_hosts` 为空且 strict 时连接会失败，提示
  管理员配置 known_hosts。
- `allow_agent=False`、`look_for_keys=False`，避免隐式使用容器内其它凭据。

## 3. 命令执行

```python
def _run(host, argv, stdin=None):
    command = " ".join(shlex.quote(arg) for arg in argv)
    chan = client.get_transport().open_session()
    ...
```

- `argv` 是列表；**禁止**拼接未转义的用户输入。
- 所有用户可控值（容器名、label 值、镜像）先经过 core 的校验；driver 再做
  一次白名单/正则校验。
- 超时由 channel 超时控制；超时抛 `ProvisionerError("TIMEOUT")`。

## 4. 方法映射

| 契约 | 远端命令 |
|---|---|
| `probe` | `docker version --format '{{.Server.Version}}'` |
| `status` | `docker inspect --format '{{json .State}}' <id>` |
| `stop` | `docker stop -t <timeout> <id>` |
| `remove` | `docker rm -f <id>` |
| `logs` | `docker logs --tail <n> --timestamps <id>` |
| `apply` | `docker inspect` → pull → `docker create` → `docker start` |

### apply 流程

1. `docker inspect --format '{{json .Config.Labels}}' <name>`；不存在按名字
   检查（`docker inspect` 返回非零即视为 missing）。
2. 找到容器后校验 `agenthub.managed=true` 与 deployment id；不符 → `CONFLICT`。
3. 比较 `agenthub.config_hash` label 与 `.Image`：
   - 相同 → `docker start`（已运行则 no-op）。
   - 不同 → `docker stop` → `docker rm -f` → 创建新容器。
4. 镜像：`docker image inspect <image>`；按 pull_policy 决定是否
   `docker pull <image>`。
5. env 写入：
   - 生成远端路径 `/tmp/agenthub-provisioner-<uuid>.env`；
   - `exec_command("umask 077; cat > <quoted path>")`，经 stdin 写入
     `KEY=VALUE` 行；
   - 关闭 stdin，检查退出码；
   - `finally` 执行 `rm -f <path>`。
6. 创建：
   ```
   docker create --name <name> --label k=v ... --env-file <path>
     --network <network> -v <vol>:<bind>:<mode> --restart <policy>
     <image> <command...>
   ```
   然后 `docker start <name>`。
7. 返回 `ContainerState`；`runtime_id` 用 `docker inspect --format '{{.Id}}'`。

## 5. 错误映射

| 场景 | code |
|---|---|
| SSH 连接/认证失败 | `UNREACHABLE` |
| 命令超时 | `TIMEOUT` |
| 同名未托管容器 | `CONFLICT` |
| 镜像缺失且禁止拉取 | `IMAGE_MISSING` |
| pull 失败 | `PULL_FAILED` |
| create/start 失败 | `CREATE_FAILED` / `START_FAILED` |
| 其它非零退出 | `SSH_COMMAND_FAILED` |

stderr 截断后再返回；core 负责最终打码。

## 6. 测试

- 注入 fake paramiko client/transport：记录 `exec_command` 的命令与 stdin。
- 断言：
  - argv 中不含任何 env value；
  - env 文件路径随机、写入内容正确、成功和异常路径都执行 `rm -f`；
  - 用户输入被 `shlex.quote`；
  - 相同 hash 不 rm/create；不同 hash 顺序为 stop → rm → create → start；
  - 未托管容器抛 `CONFLICT`；
  - strict host key 默认开启。
- 不建立真实 SSH 连接。

## 7. 被否决的方案

| 方案 | 原因 |
|---|---|
| `subprocess` 调本机 `ssh` | Odoo 镜像没有 ssh 客户端；且需要管理子进程与密码交互。 |
| 通过 SSH 端口转发 Docker socket 后复用 docker driver | 需要 streamlocal/远端 TCP，复杂度和暴露面更高。 |
| env 用 `-e KEY=VALUE` 传 | secret 出现在远端进程参数中，`ps` 可见。 |
| 关闭 host key 校验作为默认 | 中间人风险。 |
