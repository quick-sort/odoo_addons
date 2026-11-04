# AgentHub Relay — 实施进度与续接说明

> 状态快照：2026-11-01。上下文中断后从本文继续。
> 设计事实来源：`../../agenthub/docs/design.md`、`relay-v1.md`、`relay-message-envelope.md`。

## 1. 已锁定的架构决策

- Relay 持有全部实时连接（agent WS、企微 gateway）和路由/队列；Odoo 不在热路径。
- Odoo 负责：Discuss UI、agent service user、配置（agent/identity/binding）、publish outbox、异步 recorder、`mail.message` 归档。
- 目标规模：>100 agent、50 万消息/天；默认异步 recorder，lag 目标 <5s（当前 cron 版是 1 分钟）。
- `mail.message` 对齐 `llm` 语义：role/subtype、`body_json`、流式终帧一条消息。
- 每个 agent 一个唯一 service user；Discuss 里用户直接选 agent partner；企微走 `(user, channel) → agent` binding。
- thread 键：外部渠道 `agenthub:channel:<id>:peer:<peer_ref>:agent:<id>`；Discuss `discuss.channel:<id>`；命令 `command:<id>`。
- Discuss-only thread 允许 `channel_id` 为空，只挂 `discuss_channel_id`；去重靠 `relay_thread_key` 唯一。
- 热队列在 relay；Odoo 的 `agenthub.delivery` 只是审计副本。

## 2. 已完成

### 2.1 Odoo `agenthub`

模型：

- `agenthub.channel` / `agenthub.agent`（runtime、service user、token_hash、state/last_seen、workspace）
- `agenthub.identity`、`agenthub.binding`
- `agenthub.thread`（`relay_thread_key`、`discuss_channel_id`）
- `agenthub.turn`（单 thread 单活跃 turn）
- `agenthub.command`（queued 自动入 publish）
- `agenthub.delivery`（审计）
- `agenthub.publish`（outbox，HMAC、重试、dead、postcommit 立即推送）
- `agenthub.record.cursor`（recorder 拉取 checkpoint）
- `agenthub.recorder`（AbstractModel，幂等写 `mail.message`/turn/delivery，Discuss 投影）
- `agenthub.relay.config`（版本化配置快照）

其他：

- `mail.message` 扩展：role/subtype、`agenthub_body_json`、`agenthub_is_error`、`agenthub_content`、`agenthub_relay_message_id`、`agenthub_relay_turn_id`、`agenthub_stream_id`、external ids。
- 数据：`agenthub.mt_user/assistant/tool/system` subtypes。
- Cron：publish outbox、recorder 拉取。
- 安全/视图：Agents / Identities / Bindings / Commands；ACL + record rule。
- Controller：`GET /agenthub/relay/config`，Header `X-AgentHub-Config-Token`。
- 配置参数：
  - `agenthub.relay_url`
  - `agenthub.relay_secret`
  - `agenthub.relay_recorder_token`
  - `agenthub.relay_config_token`
  - `agenthub.recorder_batch_limit`

### 2.2 `agenthub_discuss`

- 新 addon：`discuss.channel._message_post_after_hook`。
- 绑定 thread 的 Discuss 用户消息 → `agenthub.publish` 的 `message.created`。
- 跳过 agent service user partner、OdooBot；事件带 `meta.origin_record_id=mail.message,<id>`。
- event_id 幂等。
- 有 README/docs/CLAUDE.md/tests。

### 2.3 `agenthub_relay`（v1 骨架，Redis 持久化）

文件：

- `envelope.py`：Pydantic envelope、event_type、role/stream/command 校验、大小限制。
- `router.py`：identity/binding 解析、确定性 `thread_key`。
- `state.py`：turn/delivery/outbox/presence 状态机、thread backlog、租约/重试/DLQ、record feed cursor。
- `protocol.py`：agent token、stream/turn 帧转 envelope。
- `wecom.py`：aibot 帧助手（subscribe/ping/ACK/callback）、`MemoryLease`/`RedisLease`、
  `RequestMap`（`req_id -> thread/agent/turn` 关联）、thread_key 解析。
- `gateway.py`：企微 gateway。`WS /v1/channel/wecom/ws` 作 aibot 服务端；
  同一 `bot_id` 单租约（跨实例拒绝、不互踢；同进程重连踢旧连接）；
  后台循环续租 + 消费 `channel.<id>.outbox` 发 `aibot_msg_callback`；
  机器人回包按 `req_id` 找回 turn，落 `origin=channel` 的 `message.updated/final`
  （只记录、不再入 outbox，避免回声）。
- `redis_state.py`：Redis 持久化实现，与 `RelayState` 同一公共契约：
  - turn/delivery/outbox 用 hash + 索引 zset；claim/lease/ack 用 Lua 保证原子。
  - thread 串行化用 `active:<thread_key>` + `backlog:<thread_key>`，Lua 原子切换。
  - record feed 是 Redis Stream，entry id 为 `<单调 seq>-0`，Odoo 的整数 cursor 直接对应；
    `record:seq` 用 INCR 持久化，重启后 cursor 不倒退。
  - 幂等键（event/message key）用带 TTL（默认 7 天）的 SETNX。
  - `ack_record` 保留 1 万条已 ack 安全余量再裁剪（Odoo 在事务提交前就发 ack）。
- `app.py`：Starlette
  - `POST /v1/publish`（HMAC）
  - `GET /v1/record` + `POST /v1/record/ack`（recorder token）
  - `WS /v1/agent/ws`、`WS /v1/channel/wecom/ws`
  - `/healthz`、`/metrics`、`/v1/admin/agents`
  - 设置 `AGENTHUB_REDIS_URL` 时使用 `RedisRelayState`，否则回退内存 store。
- `config.py`：`ConfigSnapshot`（agents/channels/identities/bindings）、`Settings`、JSON 文件快照。
- `config_sync.py`：从 Odoo `/agenthub/relay/config` 按版本拉取并原子替换缓存。
- `tests/`：envelope、router、state、protocol、HTTP/WS、config sync、Redis 持久化/重启、企微协议/租约/回环。

环境变量：

- `AGENTHUB_RELAY_HOST` / `AGENTHUB_RELAY_PORT`
- `AGENTHUB_REDIS_URL`（生产必设；不设则用内存 store）
- `AGENTHUB_PUBLISH_SECRET`
- `AGENTHUB_RECORDER_TOKEN`
- `AGENTHUB_ODOO_CONFIG_URL` / `AGENTHUB_ODOO_CONFIG_TOKEN` / `AGENTHUB_CONFIG_POLL_SECONDS`
- `AGENTHUB_CONFIG_FILE`
- `AGENTHUB_LEASE_SECONDS` / `AGENTHUB_MAX_ATTEMPTS`
- `AGENTHUB_WECOM_LEASE_SECONDS` / `AGENTHUB_WECOM_POLL_SECONDS` /
  `AGENTHUB_WECOM_REQUEST_TTL_SECONDS`

## 3. 测试与验证

### 3.1 Relay

```bash
cd /home/agent/.agent-box/workspace/_default/odoo_addons/agenthub_relay
AGENTHUB_TEST_REDIS_URL=redis://192.168.31.4:6379/15 \
  PYTHONPATH=src /app/.venv/bin/python -m pytest -q
```

结果：**56 passed**（35 基础 + 13 Redis + 8 企微；Starlette TestClient
有一条 httpx 弃用 warning，不影响）。Redis 不可达时 13 条依赖 Redis 的测试
（11 持久化 + 2 租约/RequestMap）自动 skip，结果为 43 passed / 13 skipped。
测试默认连 `redis://127.0.0.1:6379/15`，本机 docker 映射的 Redis 实际地址是
`192.168.31.4:6379`，需用环境变量覆盖。

运行：

```bash
cd /home/agent/.agent-box/workspace/_default/odoo_addons/agenthub_relay
PYTHONPATH=src /app/.venv/bin/python -m agenthub_relay.app
```

### 3.2 Odoo 测试

仓库没有挂进运行中的 `odoo` 容器，需把 addon 拷到容器 `/tmp/agenthub_test_addons`：

```bash
cd /home/agent/.agent-box/workspace/_default/odoo_addons
tar -cf - agenthub agenthub_discuss agenthub_wecom agenthub_openclaw component \
  | docker exec -i odoo sh -c 'tar -C /tmp/agenthub_test_addons -xf -'
```

测试库：`test_agenthub2`（scratch DB，已存在）。`queue_job` 不在 temp addons 路径且 `dbfilter=odoo.*`，所以必须加 `--load=web --db-filter=test_agenthub2`。

```bash
docker exec odoo odoo -d test_agenthub2 -i agenthub_discuss -u agenthub \
  --load=web --db-filter=test_agenthub2 \
  --db_host=postgres --db_user=odoo --db_password=odoo \
  --addons-path=/tmp/agenthub_test_addons,/usr/lib/python3/dist-packages/odoo/addons \
  --test-enable --test-tags /agenthub,/agenthub_discuss \
  --stop-after-init --workers=0 --no-http --http-port=0
```

结果：**0 failed / 0 error**（62 tests；含 Discuss hook、command publish、config endpoint）。

legacy 依赖：

```bash
docker exec odoo odoo -d test_agenthub2 -u agenthub_wecom,agenthub_openclaw \
  --load=web --db-filter=test_agenthub2 \
  --db_host=postgres --db_user=odoo --db_password=odoo \
  --addons-path=/tmp/agenthub_test_addons,/usr/lib/python3/dist-packages/odoo/addons \
  --test-enable --test-tags /agenthub_wecom,/agenthub_openclaw \
  --stop-after-init --workers=0 --no-http --http-port=0
```

结果：**0 failed / 0 error**（26 tests；含 relay 配置快照携带 bot_id/secret）。

## 4. 下一步（按顺序）

1. **recorder <5s SLO**（长轮询/推送 worker；当前 cron 1 分钟）。
2. **背压**（AC33：每 agent/channel 未 ack 上限，超限 429/503）与 DLQ 重放接口。
3. HA/router 分片、真实端到端 smoke。

已完成（2026-11-01）：Redis 持久化 store；企微 channel gateway（aibot WS
服务端、跨实例 bot 租约、outbox 发送、req_id 关联、channel 回包不回环）；
agent-box relay 客户端（另一仓库 `quick-sort/agent-box` PR #97：`RelayChannel`、
`thread_key → conversation_id`、`_turn_end`/`turn_finished`、`--relay` 与
legacy `--wecom` 互斥）。

## 5. 已知缺口/风险

- Redis 仍是单实例，无主从/哨兵；router 分片/多实例 HA 尚未做（AC32）。
  企微 bot 租约已做跨实例互斥（AC30 的失联接管靠 TTL 过期）。
- 幂等键默认 7 天 TTL；同一 event/message 超过 7 天重放会被当成新消息。
- record 流只按已 ack 游标裁剪（保留 1 万条安全余量），未 ack 部分无上限；
  若 Odoo recorder 长时间停机，Redis 内存会持续增长，需要监控告警。
- 未实现背压（AC33）：队列/未 ack 无上限，超限时不会拒绝新入站。
- recorder 是 1 分钟 cron，达不到 <5s SLO。
- 企微 gateway 只支持文本：媒体上传/下载、群聊语义未做；无 bot 在线时
  outbox 会一直 pending（无 TTL/告警）。
- 配置快照现在携带 `bot_id` / `secret`（仅当 channel addon 提供这些字段），
  依赖 TLS/mTLS 保护；secret 轮换后旧连接不会立即断开。
- legacy `agenthub_wecom` 与新 relay gateway 共用同一 `bot_id` 的启动校验未做。
- 附件、群聊、多用户会话语义未处理。
- `agenthub.relay.config` 返回 token hash，必须只暴露给受信 relay；目前靠 config token 保护。
- 未创建 git commit；当前工作区有大量未提交新增/修改。

## 6. 关键文件

- `agenthub/models/agenthub_{agent,thread,turn,command,delivery,publish,record_cursor,recorder,relay_config}.py`
- `agenthub/controllers/main.py`
- `agenthub/data/agenthub_{message_subtypes,cron}.xml`
- `agenthub/security/*`、`agenthub/views/*`
- `agenthub_discuss/models/discuss_channel.py`
- `agenthub/models/agenthub_relay_config.py`（channel 凭据进快照）
- `agenthub_relay/src/agenthub_relay/*`（`redis_state.py`、`gateway.py`、`wecom.py` 为新增核心）
- 设计/验收：`agenthub/docs/{design,acceptance,requirements}.md`、`agenthub/docs/relay-*.md`

## 7. 续接提示

- 动 Odoo 前先读 `agenthub/CLAUDE.md` 与 `agenthub/docs/design.md`。
- 保持红线：core 不依赖 `llm`；Discuss 用户消息按 `origin_record_id` 去重；Odoo 不在热路径。
- 每次改 Odoo 后跑上面的 `/agenthub,/agenthub_discuss` 测试，再跑 legacy 26 个。
- 每次改 relay 后跑 `pytest`；Redis 测试需要设置 `AGENTHUB_TEST_REDIS_URL`
  （本机为 `redis://192.168.31.4:6379/15`），连不上会自动 skip。
- 内存 store 仍保留作测试 fallback；改状态机时两个实现必须同步改，并补
  Redis 重启/重投测试。
