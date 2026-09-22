# agenthub_wecom — 开发约束（自动加载）

设计文档见 `docs/`，这是唯一要求来源，改代码前先读：

- `docs/requirements.md` — 业务需求与边界
- `docs/design.md` — aibot 协议、连接生命周期、多连接处理
- `docs/acceptance.md` — 验收标准（QC 唯一依据）

红线（勿违背）：

1. **只做传输，不识别对端 agent 身份。** channel 只认 `bot_id`，不得保存或
   假设「这是 OpenClaw 还是 OpenCode」。
2. **ACK 必须精确回显 `req_id` + `errcode:0`**；心跳 `ping` 必须回，否则对端
   断连重试。
3. **WS 只跑 gevent worker**，出站跨进程走 `mail.message` DB 队列，不得
   从 HTTP/cron worker 直写 socket。
