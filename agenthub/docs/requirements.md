# agenthub — 业务需求与边界

## 背景

Odoo 需要与外部 AI Agent 运行时（如 OpenClaw）对话，而这条对话跑在某个消息
传输上（如企业微信）。两者都只是「一类」，不是「唯一」：

- 传输层（channel）：企业微信只是其中一种，未来可能有 Telegram、Slack、
  邮件、网页、MCP 等。
- Agent 层（agent）：OpenClaw 只是其中一种，未来可能有内部 `llm.agent`、
  工作流引擎、人工坐席等。

如果按「Odoo ↔ 企微 ↔ OpenClaw」一对一硬编码，每新增一种传输或一种 agent
都要重写一遍路由、消息落库、状态机、重试。agenthub 的目标是把这两轴抽成
可扩展的框架，让「新增一种 channel」或「新增一种 agent」只加一个独立 addon。

## 目标

1. **core 只定义抽象**：channel / agent / thread 三个模型 + 对 `mail.message`
   的字段扩展 + 两个 component 扩展点 + 路由，不含任何具体传输或具体 agent。
   会话载体用 `mail.thread`（对齐 `llm.thread`），入口复用 Discuss 聊天界面。
2. **企微 channel 是第一个 channel 实现**：在 Odoo 内实现企业微信智能机器人
   （aibot）WebSocket 服务端，让外部 bot（如 OpenClaw 的企微插件）以
   `botId + secret + websocketUrl` 连进来。
3. **OpenClaw agent 是第一个 agent 实现**：把「用户消息交给 OpenClaw、
   拿回 OpenClaw 的回复」封装成一个 agent 类型。
4. 与仓库既有分层模式对齐：`infohub_channel_*` 的 channel 扩展方式、
   `llm_*` 的 provider 扩展方式，都用 component + `selection_add`，core 保持干净。

## 范围

### 在范围内

- `agenthub` core：3 个模型 + `mail.message` 扩展 + 扩展点 + 路由 + 投递状态机。
- `agenthub_wecom`：aibot WebSocket 服务端（认证、心跳、收发、多连接），
  对端 agent 无关。
- `agenthub_openclaw`：OpenClaw 的对话语义（回包解析/流式累积/媒体卡片），
  传输无关。

### 明确不做（本阶段）

- **不实现真实企微后台的 Agent 模式**（自建应用 HTTP 回调的 XML/AES 加解密、
  `qyapi.weixin.qq.com` 主动发送 API）。那是另一种 channel 形态，与 aibot
  长连接是两条独立协议，另开 addon 处理。
- **core 不依赖 `llm`。** 只有将来某个 agent 实现需要内部 LLM 时才引入，且
  封闭在该扩展 addon 内（类比 `infohub_channel_mcp` 依赖 `llm`）。
- **不做多级路由/复杂的 agent 自动选择**。MVP 只做显式绑定：一个 thread
  （channel + peer）绑定一个 agent。自动路由规则留到以后。
- **不做消息的多端同步/已读回执等 IM 级语义**，只保证消息可靠落库与投递。
- 不碰生产端口（8069/8072/5432 等），WebSocket 只服务在 gevent worker。
