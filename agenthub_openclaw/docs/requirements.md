# agenthub_openclaw — 业务需求与边界

## 背景

OpenClaw 是 `agenthub` 要对接的第一个外部 Agent 运行时。它通过企微 aibot
协议连进 Odoo（见 `agenthub_wecom`），但「和 OpenClaw 对话该怎么理解」是它
自己的语义，与传输无关。

本 addon 只实现 **OpenClaw 的对话语义**——怎么组织一条提问、怎么理解
OpenClaw 的回包。它不实现任何传输：消息怎么送出去、回包怎么回来，是 core
路由 + 具体 channel 的事。

## 目标

1. 作为 `agenthub.agent` 的一个 `agent_type` 实现，挂进 core 路由。
2. 解析 OpenClaw 的流式回包：同 `stream.id` 多帧累积、`finish` 收尾，得到
   完整回复。
3. 处理 OpenClaw 特有的内容：`<think>` 思考块、markdown 正文、（预留）媒体/
   模板卡片指令。
4. 用 `agenthub_reply_to_external_id` 把回包关联回原提问。

## 范围

### 在范围内

- 流式回包累积与终帧判定。
- `<think>` 块与正文分离。
- 用 `agenthub_reply_to_external_id` 关联回原 outbound。
- 产出 outbound `mail.message`（最终回复）交 core 路由。

### 明确不做（本阶段）

- **不实现媒体/模板卡片指令的落地**（`MEDIA:` 指令、`template_card`）——先
  跑通文本，媒体/卡片依赖 `agenthub_wecom` 的媒体能力，后续加。
- **不实现传输。** 本 addon 不 import 任何具体 channel addon（尤其
  `agenthub_wecom`）。
- **不实现 OpenClaw 的配置下发/管理**（往 OpenClaw 推配置等），只做对话。
