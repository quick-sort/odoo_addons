# agenthub_provisioner_ssh — 验收标准（QC 唯一依据）

## 测试边界

- 命令：`--test-tags /agenthub_provisioner_ssh`。
- 使用 fake paramiko/transport；不建立真实 SSH 连接、不发网络请求。

## 1. 装载与依赖

- [ ] **AC-S1** 模块干净装载：`-u agenthub_provisioner_ssh` 退出码 0。
- [ ] **AC-S2** `depends` 含 `agenthub_provisioner`；manifest 的
  `external_dependencies` 含 Python `paramiko`。
- [ ] **AC-S3** core 不 import `paramiko`；只有本 addon 导入它。

## 2. 扩展点与字段

- [ ] **AC-S4** `driver_type` 增加 `ssh`；host 表单出现
  `ssh_host`/`ssh_port`/`ssh_user`/`ssh_private_key`/`ssh_known_hosts`/
  `ssh_strict_host_key`/`remote_docker` 字段。
- [ ] **AC-S5** `host._driver()` 对 `driver_type=ssh` 解析到
  `agenthub.provisioner.driver.ssh`。
- [ ] **AC-S6** `ssh_private_key` 与 `ssh_key_passphrase` 仅 system 组可读写。

## 3. 连接与安全

- [ ] **AC-S7** 默认 `ssh_strict_host_key=True` 且使用 `RejectPolicy`；
  关闭时显式使用 `AutoAddPolicy`。
- [ ] **AC-S8** 连接参数使用配置的 host/port/user，且
  `allow_agent=False`、`look_for_keys=False`。
- [ ] **AC-S9** 私钥解析支持 RSA/ECDSA/Ed25519；解析失败抛
  `ProvisionerError(code="UNREACHABLE")`。
- [ ] **AC-S10** SSH 认证/连接失败映射为 `UNREACHABLE`，错误信息不含私钥。

## 4. 命令与 env

- [ ] **AC-S11** 每条远端命令由 argv 列表经 `shlex.quote` 生成；测试用含
  空格、引号、分号的容器名验证转义。
- [ ] **AC-S12** env 不以 `-e`/命令行传递；写入远端随机临时文件，权限为
  0600（`umask 077`）。
- [ ] **AC-S13** env 文件在成功路径和异常路径都被 `rm -f` 清理。
- [ ] **AC-S14** env 内容按 `KEY=VALUE` 行写入；不含 secret 的命令行参数。
- [ ] **AC-S15** 命令超时抛 `ProvisionerError(code="TIMEOUT")`。

## 5. apply / stop / remove / status / logs

- [ ] **AC-S16** 容器不存在时执行 pull（按策略）→ create → start，
  参数（name、labels、env-file、network、volumes、restart、image、command）
  与 spec 一致。
- [ ] **AC-S17** 相同 config hash 与镜像时只确保 running，不执行 rm/create。
- [ ] **AC-S18** 不同 config hash 时顺序为 stop → rm → create → start。
- [ ] **AC-S19** 同名容器缺少 `agenthub.managed=true` 或 deployment id 不符
  时抛 `CONFLICT`，不执行 stop/rm。
- [ ] **AC-S20** `stop` 使用配置的 timeout；不存在的容器是 no-op。
- [ ] **AC-S21** `remove` 使用 `rm -f`；不存在是 no-op。
- [ ] **AC-S22** `status` 解析 `docker inspect` 的 State JSON，缺失时返回
  `status="missing"`。
- [ ] **AC-S23** `logs` 使用 `--tail` 并返回解码后的文本。

## 6. 错误与测试约束

- [ ] **AC-S24** 非零退出按 design.md 映射为 `ProvisionerError`；stderr
  截断且不包含 env。
- [ ] **AC-S25** 全部测试使用 fake transport，不产生真实 SSH/网络调用。
- [ ] **AC-S26** 所有 view/security XML 通过 `xml.dom.minidom` 解析。
