# agenthub_openclaw — 系统设计

## 定位

`agenthub` 的第一个 agent 实现：OpenClaw 的**对话语义**。它不碰传输——
消息怎么送到 OpenClaw、回包怎么回来，是 core 路由 + 具体 channel 的事。

因此 `agenthub_openclaw` 与 `agenthub_wecom` **互不依赖**，两者都只依赖
`agenthub` core。把 OpenClaw 接到企微上，是在 Odoo 里建一条
`thread(channel=企微 bot X, agent=OpenClaw)` 的运行时绑定。

## 数据模型

继承 core 的 `agenthub.agent`，追加本 agent 的配置：

- `agent_type`：`selection_add=[("openclaw", "OpenClaw")]`
- 无传输字段（不存 channel/bot 信息）——经哪条 channel 触达由 `thread` 决定。

## 职责：对话语义

OpenClaw 的「大脑」在 OpenClaw 运行时侧，本 addon 是 Odoo 侧的「手柄」，
负责把一次对话的原始帧变成一条干净的回复。核心是三件事：

### 1. 流式回包累积

OpenClaw 对一次提问的回包是流式的：多个 `finish=false` 增量帧 + 一个
`finish=true` 终帧，共用同一个 `stream.id`。agent 提供 `accumulate_stream`
纯函数把一组帧折叠成完整文本，`finish=true` 判定收尾。

把多帧折叠成**一条 `mail.message` 原地更新**（对齐 `llm.thread` 的
`message_post_from_stream`）属于 channel 的传输层帧折叠，当前阶段待 e2e 落地；
本 addon 只交付纯函数语义。

### 2. 内容归一化

- 剥离 `<think>…</think>` 思考块，与可见正文分开。
- 保留正文 markdown。
- （预留）识别 `MEDIA:` 指令与模板卡片，待 `agenthub_wecom` 具备媒体能力后
  落地；本阶段遇到则忽略并留日志。

### 3. 关联

用 `agenthub_reply_to_external_id` 把回包关联回原 outbound（core 的提问）。
channel 在归一化时填好这个字段，agent 只消费它，从而完全不知道 channel 的
实现。

## 与 core 的接口

作为 `agenthub.agent` 的 `agent_type="openclaw"` 实现：

- `agenthub.agent.openclaw` component：`reply(agent, message)` 输入一个 inbound
  `mail.message`（OpenClaw 的回包），返回归一化后的可见文本（剥掉 `<think>`）。
- agent 只操作 `mail.message` 的字段（含 `agenthub_*` 扩展），不 import 任何
  channel addon。

## 一轮对话的数据流（示意）

```
Odoo 提问方 ──建 outbound mail.message("用户问题", delivery_state=pending)──> core 路由 ──> channel.send()
                                                                                    │ aibot_msg_callback
                                                                                    ▼
                                                                        OpenClaw 运行时
                                                                                    │ aibot_respond_msg ×N（流式）
                                                                                    ▼
channel 归一化 inbound mail.message(agenthub_reply_to_external_id 关联) ──> core 路由 ──> agent.reply()
                                                                                    │ 累积+归一化（一条 mail.message 原地更新）
                                                                                    ▼
                                                            outbound mail.message("最终回复") ──> 提问方
```

## 被否决的方案

| 方案 | 否决理由 |
|---|---|
| `agenthub_openclaw` 依赖 `agenthub_wecom` | 在代码里断言「OpenClaw 只能走企微」；传输与语义应解耦，绑定交给 thread。 |
| 把流式累积/think 剥离放进 channel | 这些是 OpenClaw 的语义，不是企微协议的一部分；换 agent 就要换 channel，反了。 |
| agent 直连 socket 取回包 | 回包经 core 路由 + channel 归一化后到 agent，直连会破坏解耦与跨进程投递。 |
