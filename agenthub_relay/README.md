# agenthub-relay

AgentHub 的实时消息层。当前实施进度与续接说明见 `docs/implementation-status.md`。
设计文档在 `../agenthub/docs/`：

- `relay-v1.md` — 职责、状态机、接口
- `relay-message-envelope.md` — 统一 envelope

## 当前骨架

已实现：

- Pydantic envelope 校验（`envelope.py`）
- identity/binding 路由与确定性 `thread_key`（`router.py`）
- turn/delivery/outbox/presence 状态机与内存存储（`state.py`）
- Redis 持久化 store（`redis_state.py`）：turn/delivery/outbox/presence 与
  record feed 全部落 Redis，重启后队列、租约和 record cursor 不丢失
- agent WebSocket 协议助手（`protocol.py`）
- 企微 aibot channel gateway：`/v1/channel/wecom/ws`、bot Redis 租约、outbox 发送、
  `req_id` 回执关联（`wecom.py`、`gateway.py`）
- Starlette HTTP API：`/v1/publish`、`/v1/record`、`/v1/record/ack`、`/v1/agent/ws`、`/healthz`（`app.py`）
- Odoo recorder 对接：`/v1/record` + `/v1/record/ack` 带 recorder token；Odoo 侧 cron 拉取并幂等写 `mail.message`、Discuss 投影
- pytest 单元测试（`tests/`）

尚未实现（后续）：

- agent-box relay 客户端（WS、`thread_key ↔ session_id`）
- HA/router 分片、DLQ 管理界面
- Odoo recorder 的长轮询/推送 worker（当前是 1 分钟 cron，<5s SLO 待补）
- 未 ack 上限/背压（当前只做状态机，不做拒绝）
- 企微媒体上传/下载（当前只支持文本帧）

## 运行

```bash
cd agenthub_relay
PYTHONPATH=src python -m agenthub_relay.app
```

环境变量：

- `AGENTHUB_RELAY_HOST`（默认 `127.0.0.1`）
- `AGENTHUB_RELAY_PORT`（默认 `8090`）
- `AGENTHUB_PUBLISH_SECRET`（默认 `dev-secret`，生产必须覆盖）
- `AGENTHUB_REDIS_URL`（设置后使用 Redis 持久化 store；未设置则用内存 store，仅适合测试）
- `AGENTHUB_RECORDER_TOKEN`（默认 `dev-recorder`，Odoo recorder 拉取 record feed 时携带）
- `AGENTHUB_CONFIG_FILE`（Odoo 配置快照 JSON，静态兜底）
- `AGENTHUB_ODOO_CONFIG_URL` + `AGENTHUB_ODOO_CONFIG_TOKEN`（从 Odoo 拉取版本化配置快照）
- `AGENTHUB_CONFIG_POLL_SECONDS`（默认 15 秒）
- `AGENTHUB_LEASE_SECONDS`、`AGENTHUB_MAX_ATTEMPTS`
- `AGENTHUB_WECOM_LEASE_SECONDS`（默认 90）、`AGENTHUB_WECOM_POLL_SECONDS`（默认 0.5）、
  `AGENTHUB_WECOM_REQUEST_TTL_SECONDS`（默认 86400）

## 测试

```bash
cd agenthub_relay
PYTHONPATH=src python -m pytest -q
```

Redis 相关测试需要可达的 Redis；默认连 `redis://127.0.0.1:6379/15`，
可用 `AGENTHUB_TEST_REDIS_URL` 覆盖，连不上时自动 skip。
