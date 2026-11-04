# agenthub_provisioner — 验收标准（QC 唯一依据）

## 测试边界

- 命令：`docker exec odoo odoo -c /etc/odoo/odoo.conf -d <test_db> -i agenthub_provisioner --test-enable --test-tags /agenthub_provisioner --stop-after-init --workers=0 --no-http`。
- 不连接真实 Docker 或 SSH；driver 用 fake 实现/注入。
- driver addon（docker/ssh）的专属验收在各自 `docs/acceptance.md`。
- 本文 AC 编号是 core 的合同；`tests/` 与之一一对应。

## 1. 装载与依赖

- [ ] **AC1** 模块干净装载：`-u agenthub_provisioner` 退出码 0。
- [ ] **AC2** `depends` 含 `agenthub`、`component`、`queue_job`；**不含**
  `docker`/`paramiko`/`llm`/任何 driver addon。测试断言依赖列表。
- [ ] **AC3** 三个 driver addon 都以 `agenthub_provisioner` 为依赖，且
  core 源码不 import `docker`、`paramiko`。

## 2. 模型与约束

- [ ] **AC4** `agenthub.provisioner.host`、`agenthub.provisioner.llm`、
  `agenthub.agent.deployment` 存在。
- [ ] **AC5** `agenthub.provisioner.host` 继承 `collection.base`（可
  `work_on()`）；`driver_type` 在 core 源码中为 `selection=[]`。
- [ ] **AC6** `agenthub.agent.deployment.agent_id` 唯一；同一 agent 不能有
  两个 deployment。
- [ ] **AC7** `container_name` 唯一，且不匹配
  `^[A-Za-z0-9][A-Za-z0-9_.-]{1,62}$` 时抛 `ValidationError`。
- [ ] **AC8** `mode=relay` 但无 relay 地址（自身与 host 默认都为空）时
  Apply 报用户错误。
- [ ] **AC9** `mode=odoo_discuss` 时缺少 `odoo_url`/`odoo_db`/`odoo_login`/
  `odoo_api_key` 任一字段，Apply 报用户错误。
- [ ] **AC10** `extra_env` 的非法 key（非 `[A-Z_][A-Z0-9_]*`）、含换行/NUL 的
  value、以及保留 key `RELAY_AGENT_ID`/`RELAY_AGENT_TOKEN` 均被拒绝。
- [ ] **AC11** `agenthub.agent` 上存在 `provisioner_token_version`
  （默认 1）和 `deployment_ids`。

## 3. Component 扩展点

- [ ] **AC12** 抽象 component `agenthub.provisioner.driver` 存在，collection
  为 `agenthub.provisioner.host`，方法包含
  `probe/apply/stop/remove/status/logs`。
- [ ] **AC13** `host._driver()` 按 `usage == driver_type` 解析；未注册的
  driver type 抛 `UserError`，错误信息包含类型名。
- [ ] **AC14** 两个不同 usage 的 driver 可同时注册且互不冲突
  （`SeveralComponentError` 不出现）。
- [ ] **AC15** 抽象方法未实现时抛 `NotImplementedError`（与 core 其他扩展点一致）。

## 4. 环境变量与 token

- [ ] **AC16** env 优先级为 host 默认 < relay/odoo 派生 < LLM profile <
  `extra_env`；测试覆盖每一层覆盖。
- [ ] **AC17** relay 模式渲染 `RELAY_URL`、`RELAY_AGENT_ID`、
  `RELAY_AGENT_TOKEN`、`RELAY_HEARTBEAT_SECONDS`；odoo 模式渲染 5 个
  `ODOO_*` 变量。
- [ ] **AC18** LLM profile 按 `auth_mode` 渲染 `ANTHROPIC_API_KEY` 或
  `ANTHROPIC_AUTH_TOKEN`，并渲染 base URL 与四个模型变量。
- [ ] **AC19** `_render_env_preview()` 对 key 含 `KEY/TOKEN/SECRET/PASSWORD`
  的值打码；`last_error` 写入前同样打码。
- [ ] **AC20** 派生 token 对同一 `(agent_id, version, secret)` 稳定；version
  改变后 token 与 `agent.token_hash` 都改变。
- [ ] **AC21** Apply 后 `agent.token_hash == sha256(token)`；数据库中不存在
  该 token 的明文字段。
- [ ] **AC22** 缺少 `AGENTHUB_PROVISIONER_TOKEN_SECRET` 且
  `ir.config_parameter` 未配置时，Apply 报错并提示两种配置方式。

## 5. Spec 与幂等

- [ ] **AC23** `config_hash` 对同一份
  `{image, command, env, volumes, network, restart_policy}` 稳定；任一变化
  产生不同 hash。
- [ ] **AC24** spec 携带 `agenthub.managed=true`、`agenthub.agent_id`、
  `agenthub.deployment_id`、`agenthub.config_hash` 四个 label。
- [ ] **AC25** 默认卷把 `<container_name>-home` 挂到 `/home/agent`；
  默认命令按 mode 为 `--relay` 或 `--odoo`。
- [ ] **AC26** 相同 hash 重复 Apply 不调用 driver 的 remove/create
  （只确保 running）。
- [ ] **AC27** 不同 hash 或不同镜像 Apply 时，driver 收到“先 stop、再 remove、
  再 create”的顺序调用。
- [ ] **AC28** 同名容器缺少 `agenthub.managed=true` 或 deployment id 不符时，
  driver 的 apply 抛 `ProvisionerError(code="CONFLICT")`，容器不被修改。

## 6. 生命周期

- [ ] **AC29** Apply 把 `desired_state` 置 running、`state` 置
  provisioning，并投递一个 `root.agenthub` 的 queue job。
- [ ] **AC30** job 成功后 `state=running`、`runtime_id` 非空、
  `config_hash` 与 spec 一致；失败后 `state=error` 且 `last_error` 非空。
- [ ] **AC31** Stop 成功后 `state=stopped`、`desired_state=stopped`；
  对已停止/不存在的容器是 no-op。
- [ ] **AC32** Remove 成功后 `state=removed`、`desired_state=absent`、
  `runtime_id` 清空；对不存在的容器是 no-op。
- [ ] **AC33** Rotate token 先 bump version、写新 hash，再触发 Apply。
- [ ] **AC34** 同一 deployment 的并发 Apply/Stop 由 queue_job
  `identity_key` 串行化，不会出现两个 job 同时操作同一容器。

## 7. 状态同步与 reconciliation

- [ ] **AC35** `action_sync()` 调用 driver.status，更新 `runtime_id`、
  `state`、`last_status_at`；容器缺失时按 desired_state 落到
  error 或 stopped。
- [ ] **AC36** 容器 label 的 `config_hash` 与当前 spec hash 不一致时
  `config_drift=True`；一致时 False。
- [ ] **AC37** cron reconciliation 探测 active hosts；探测失败的 host
  置 offline/error，但不把其上的 deployment 批量标错。
- [ ] **AC38** `state` 为 provisioning/stopping 的 deployment 在 cron 中
  被跳过。
- [ ] **AC39** `auto_heal=False`（默认）时，容器缺失只标记状态，不自动
  Apply；`auto_heal=True` 且 desired running 时才触发 Apply。

## 8. 安全与权限

- [ ] **AC40** 非 `base.group_system` 用户对 host/deployment/llm profile
  的 create/write/unlink 被拒绝（ACL）。
- [ ] **AC41** secret 字段（`llm.secret`、`odoo_api_key`、
  `provisioner_token_version`）仅 system 组可读写。
- [ ] **AC42** 镜像不匹配
  `agenthub.provisioner.allowed_images`（默认 `ghcr.io/quick-sort/agent-box:*`）
  时 Apply 被拒绝。
- [ ] **AC43** deployment 只能由 system 用户执行 Apply/Stop/Remove/Sync/
  Rotate；普通用户即使能读也不能执行。

## 9. UI 与 XML

- [ ] **AC44** 存在 `Agent Hub → Provisioning → Hosts / Deployments /
  LLM Profiles` 菜单与 list/form 视图。
- [ ] **AC45** deployment 表单有 statusbar 与 Apply/Stop/Remove/Sync/
  Rotate/Logs 按钮；agent 表单有 deployment smart button。
- [ ] **AC46** 所有 view/security/data XML 通过 `xml.dom.minidom` 解析。

## 10. 可观测与错误

- [ ] **AC47** `action_logs()` 返回最近 `logs_tail` 行，且结果经过打码。
- [ ] **AC48** driver 抛 `ProvisionerError` 时，`last_error` 包含 code 与
  detail，且不含任何 secret 值。
- [ ] **AC49** job 失败不会无限重试：错误被记录后 job 正常结束。

## 11. 测试约束

- [ ] **AC50** 全部测试不发起真实 Docker API / SSH / 网络调用；无 API key
  也能通过。
- [ ] **AC51** 每个 AC 至少有一个测试；测试文件在 `tests/__init__.py` 中导入。
