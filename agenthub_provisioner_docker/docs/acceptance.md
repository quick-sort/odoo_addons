# agenthub_provisioner_docker — 验收标准（QC 唯一依据）

## 测试边界

- 命令：`--test-tags /agenthub_provisioner_docker`。
- 使用 fake Docker client；不连接真实 socket、不拉取镜像、不发网络请求。

## 1. 装载与依赖

- [ ] **AC-D1** 模块干净装载：`-u agenthub_provisioner_docker` 退出码 0。
- [ ] **AC-D2** `depends` 含 `agenthub_provisioner`；manifest 的
  `external_dependencies` 含 Python `docker`。
- [ ] **AC-D3** core 不 import `docker`；只有本 addon 导入它。

## 2. 扩展点

- [ ] **AC-D4** `driver_type` 增加 `docker`；host 表单出现
  `docker_url`、`docker_timeout`、`docker_tls*` 字段。
- [ ] **AC-D5** `host._driver()` 对 `driver_type=docker` 解析到
  `agenthub.provisioner.driver.docker`，usage 为 `docker`。

## 3. 连接

- [ ] **AC-D6** `probe()` 调 `client.ping()` 并返回 engine 版本；异常返回
  `HostProbe(ok=False, detail=...)`。
- [ ] **AC-D7** `docker_url` scheme 不是 `unix`/`tcp` 时抛 `ProvisionerError`。
- [ ] **AC-D8** `tcp://` 非 loopback 且 `docker_tls=False` 时拒绝连接。
- [ ] **AC-D9** TLS 开启时客户端使用 `TLSConfig(verify=True)` 与配置的
  CA/cert/key 路径。

## 4. apply

- [ ] **AC-D10** 容器不存在时按 spec 创建：name、image、command、env、
  volumes、network、labels、restart policy 与 spec 一致，并启动。
- [ ] **AC-D11** 相同 config hash 与镜像时只确保 running，不调用
  stop/remove/create。
- [ ] **AC-D12** 不同 config hash 时调用顺序为 stop → remove → create →
  start，且新容器使用新 env。
- [ ] **AC-D13** 同名容器缺少 `agenthub.managed=true` 时抛
  `ProvisionerError(code="CONFLICT")`，不执行 stop/remove。
- [ ] **AC-D14** 同名容器 managed label 的 deployment id 不符时同上。
- [ ] **AC-D15** `pull_policy=always` 调用 pull；`missing` 仅在本地不存在时
  pull；`never` 且不存在抛 `IMAGE_MISSING`。

## 5. stop / remove / status / logs

- [ ] **AC-D16** `stop()` 调 `container.stop(timeout=...)`；容器不存在或
  已停止是 no-op。
- [ ] **AC-D17** `remove()` 调 `container.remove(force=True)`；不存在是 no-op。
- [ ] **AC-D18** `status()` 返回 `ContainerState`，正确映射
  created/running/exited/dead 与 image/health；不存在时 `status="missing"`。
- [ ] **AC-D19** `logs()` 返回最后 `tail` 行并解码为字符串。

## 6. 错误与安全

- [ ] **AC-D20** SDK 异常按 design.md 的 code 映射为 `ProvisionerError`。
- [ ] **AC-D21** 错误信息不包含 env 值或 secret。
- [ ] **AC-D22** 所有测试使用 fake client，不产生真实 Docker 调用。

## 7. XML

- [ ] **AC-D23** 所有 view/security XML 通过 `xml.dom.minidom` 解析。
