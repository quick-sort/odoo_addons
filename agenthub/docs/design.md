# agenthub — 系统设计

## 总览：两轴正交、运行时绑定

agenthub 把「Odoo 与外部智能对话」拆成两轴，各轴独立扩展：

- **channel（传输）** —— 消息从哪条线上进来、往哪条线出去。企微、Telegram、
  网页… 是 channel 的具体取值。
- **agent（应答）** —— 一个「对话对象」是谁、怎么理解它的消息。OpenClaw、
  OpenCode、内部 `llm.agent`、人工… 是 agent 的具体取值。

两者**正交且不耦合**：

- 一条 channel 上跑的是谁，channel 本身**不知道也不该知道**——从企微收到的
  消息，无法区分对端是 OpenClaw、OpenCode 还是任何实现了企微 aibot 插件的
  运行时。channel 只认对端的传输标识（企微的 `bot_id`）。
- 一个 agent 经哪条 channel 触达，agent 本身**也不关心**——它只负责「这段
  对话该怎么理解、怎么应答」。

谁配谁，由 `agenthub.thread` 在**运行时绑定**（一条数据，不是代码依赖）：一个
会话（channel + peer）绑定一个 agent。channel addon 与 agent addon 都只依赖
core。

会话的**载体是 `mail.thread`**（对齐 `llm.thread`）：消息用标准 `mail.message`
存储，天然获得 Discuss 聊天界面、附件、流式推送，流式回复用「一条消息原地
更新」表达。

## 数据模型

三个模型都在 `agenthub` core，namespace 在 `agenthub.*`；再加一个对
`mail.message` 的字段扩展。

### agenthub.channel（传输）

继承 `collection.base`（component 的 collection）。字段：

- `channel_type`：Selection，**core 置空**，由各 channel addon `selection_add`
  填充。
- `name`、`active`
- 健康状态：`last_run_at` / `error_count` / `last_error`

**core 不预置任何 channel 专属字段**（企微的 `bot_id`/`secret`、Telegram 的
`bot_token` 都由各自 addon 用 `_inherit` 追加）。

### agenthub.agent（应答）

继承 `collection.base`。字段：

- `agent_type`：Selection，**core 置空**，由各 agent addon `selection_add`
  填充。
- `name`、`active`

同样不预置 agent 专属字段。

### agenthub.thread（会话 = 运行时绑定 + 聊天载体）

继承 `mail.thread`（像 `llm.thread`）。字段：

- `name`：标题
- `channel_id`：M2o `agenthub.channel`，怎么到达
- `peer_ref`：Char，channel 侧的对端标识（企微的 `bot_id`，Telegram 的
  chat id…）
- `agent_id`：M2o `agenthub.agent`，谁来应答
- `external_id`：channel 侧稳定标识，用于幂等/去重
- `state`：`active` / `closed`
- 唯一约束 `(channel_id, peer_ref)`：同一 channel 上的同一 peer 只有一个会话

继承 `mail.thread` 意味着：消息就是 `mail.message`，可直接在 Discuss 界面里
聊，流式与附件的 UI/推送都复用标准机制。

### mail.message 扩展（会话内容 + 传输状态）

`_inherit = "mail.message"`，给消息加 agenthub 专属字段（core 不依赖 `llm`，
用 agenthub 自己的字段，不借用 `llm_role`）：

- `agenthub_role`：`user`（Odoo 侧）/ `assistant`（外部 agent 侧），供 UI 区分
  气泡
- `agenthub_direction`：`in`（从 channel 进来）/ `out`（要发往 channel）
- `agenthub_external_id`：channel 侧消息 id（企微的 `msgid` / `req_id`），用于
  关联与去重
- `agenthub_reply_to_external_id`：channel 侧「这条消息在回复谁」的关联 id
  （企微 `aibot_respond_msg` 回传的 `req_id`），把回包关联回原 outbound
- `agenthub_delivery_state`：`pending` / `sent` / `failed`——出站投递状态机，
  也是跨进程出站队列的载体
- `agenthub_stream_id`：流式累积关联（同一次流式回复的多帧共用）
- `agenthub_content`：channel 侧**原始内容**（HTML 渲染前），agent 读它解释
  消息（如 OpenClaw 的 `<think>` 块）

**出站队列直接落在 `mail.message` 上**：`agenthub_delivery_state=pending` 的
outbound 消息就是要投递的队列项。不单开 `agenthub.message` 表，避免「内容」
与「投递状态」两张表同步。

流式回复对齐 `llm.thread` 的 `message_post_from_stream`：首帧建占位消息，逐帧
原地 `write` 累积内容（原始 markdown 存 `body_json`），终帧收尾。

## 扩展点

core 定义两个抽象 component，各自的具体类型用 **usage 后缀** 消歧（与
InfoHub 一致，绕开 `SeveralComponentError`）：

```
WorkContext(model_name=..., collection=channel).component(
    usage=channel.channel_type)
WorkContext(model_name=..., collection=agent).component(
    usage=agent.agent_type)
```

（usage 等于类型值，如 `"wecom"` / `"openclaw"`，由 component 的 `_collection`
限定到对应模型，对齐 `llm.provider.adapter` 的用法，而非 InfoHub 的前缀后缀式。）

### agenthub.channel 契约（传输，agent 无关）

- `send(channel, message)`——把一个 outbound `mail.message` 投递到对端。这是
  core 路由唯一需要调用的抽象契约。
- 入站归一化与连接生命周期（企微的 gevent 循环）是 channel 内部实现，由
  channel 自己的控制器驱动，不进抽象契约。

### agenthub.agent 契约（应答，channel 无关）

- `reply(agent, message)`——给定一个 inbound `mail.message`，返回归一化后的
  回复内容（文本）。
- agent 只操作 `mail.message` 的内容与关联，不触碰任何具体 channel 的传输。

## 路由与数据流（core 中介）

core 的路由层是 channel 与 agent 之间唯一的中介，两者互不直接调用：

入站（外部 → Odoo → agent → 外部）：

1. channel 收到传输事件，归一化成 inbound `mail.message`，按
   `(channel_id, peer_ref)` 找/建 thread 并落库
2. core 路由取 `thread.agent_id`，调 `agent.reply(inbound)`
3. agent 产出 outbound `mail.message`，core 路由交 `channel.send()` 投递

出站（Odoo 主动发起，例如 Odoo 作为「用户」向外部 agent 提问）：

1. 业务侧（Discuss 界面 / cron）在某个 thread 下建 outbound `mail.message`
   （`agenthub_delivery_state=pending`）
2. gevent worker 的 channel 连接循环轮询「本 channel 的 pending」→ `send()`
   → 置 `sent`
3. 外部 agent 的回包作为 inbound 回来（`agenthub_reply_to_external_id` 关联到
   原 outbound），core 路由交 agent 解释、落库、投递给发起方

一轮「提问→应答」的关联由 `agenthub_external_id` / `agenthub_reply_to_external_id`
串起来：channel 负责在归一化时填这两个字段，agent 负责用它们匹配，谁都不
需要知道对方的实现。

## 企微 channel（agenthub_wecom）

### 协议定位

实现企业微信智能机器人（aibot）**WebSocket 服务端**。对端是外部 agent
运行时装的企微插件（`@wecom/aibot-node-sdk` 客户端），它主动 `ws://` 连进来，
用 `bot_id + secret` 认证，之后双方用 JSON 文本帧 `{cmd, headers:{req_id},
body}` 通信。

命令集（以 SDK 为准，插件源码里 `aibot_callback`/`aibot_response` 是过时命名）：

| 方向 | cmd | 语义 |
|---|---|---|
| C→S | `aibot_subscribe` | 认证 `{bot_id, secret, scene?, plug_version?}` |
| C→S | `ping` | 心跳（30s） |
| C→S | `aibot_respond_msg` | 被动回复（对某回调的流式/文本回复） |
| C→S | `aibot_send_msg` | 主动发送 |
| C→S | `aibot_upload_media_init/_chunk/_finish` | 分片上传换 `media_id` |
| S→C | `aibot_msg_callback` | 推给 bot 的「用户消息」 |
| S→C | `aibot_event_callback` | 事件（`enter_chat` / `disconnected_event` …） |
| S→C | （无 cmd） | 所有 ACK：`{headers:{req_id}, errcode, errmsg}` |

三条硬规则（决定连接能否稳定）：

1. **认证**：subscribe 回 `errcode:0` 即成功，非 0 客户端断连重试。
2. **心跳**：`ping` 必须回显 `req_id` + `errcode:0`，否则客户端判定连接死亡。
3. **ACK**：`respond`/`send`/`upload_*` 每个都要按 `req_id` 精确回显 ACK，
   否则客户端 reject/超时。

**channel 只认 `bot_id`**：认证成功后只记录「bot_id ↔ 连接」，不关心、也不
保存「这个 bot 背后是 OpenClaw 还是 OpenCode」。那是 thread 绑定层的事。

### 多连接处理

三件事：

1. **按 bot_id 区分**：认证成功后 `_live_connections[bot_id] = conn`（gevent
   worker 进程内）。
2. **同 bot_id 互踢**：新 subscribe 到来时，若已有同 bot_id 连接，先给旧连接
   推 `aibot_event_callback(eventtype=disconnected_event)` 再关旧 socket，然后
   接管。这复刻了真实企微服务端行为，也让外部运行时侧的双实例互踢死循环
   得以避免。
3. **跨进程下发走 DB**：注册表是 gevent worker 进程内内存态；HTTP/cron
   worker 是另一个进程，拿不到 socket。所以 Odoo → 外部 agent 的消息落
   `mail.message`（`agenthub_delivery_state=pending`），由连接循环轮询本
   channel 的 pending 投递；多 gevent worker 用 `SELECT … FOR UPDATE SKIP
   LOCKED` 抢占，保证只有持有该 bot 连接的那个 worker 投递。

### 与 Odoo 的承载关系

WebSocket 只跑在 Odoo **gevent worker**（8072），路由用
`@route('/wecom/aibot/ws', type='http', auth='public', websocket=True)` 做
HTTP→WS 升级，握手后 `call_on_close` 里进入连接循环。生产由 nginx 反代，
不碰 8069。

## OpenClaw agent（agenthub_openclaw）

### 定位

`agenthub_openclaw` 只实现「与 OpenClaw 对话的**语义**」——怎么组织一条提问、
怎么理解 OpenClaw 的回包（流式多帧 `stream.id` 累积、`finish` 收尾、markdown、
`<think>` 块、媒体/模板卡片指令）。它**不实现传输**：消息怎么送出去、回包
怎么回来，是 core 路由 + 具体 channel 的事。

因此 `agenthub_openclaw` 与 `agenthub_wecom` **互不依赖**，两者都只依赖
`agenthub` core。把 OpenClaw 接到企微上，是在 Odoo 里建一条
`thread(channel=企微 bot X, agent=OpenClaw)` 的运行时绑定，而非代码耦合。

### 语义边界

- agent 用 `agenthub_reply_to_external_id` 把回包关联回原 outbound，用流式
  多帧累积出完整回复（一条 `mail.message` 原地更新），再交 core 路由投递。
- 流式中间帧与终帧、媒体/卡片指令的解析，都是 OpenClaw 的语义，封闭在本
  addon；换一个 agent（如 OpenCode）就在它自己的 addon 里写它自己的语义。

## 关键取舍与理由

### 为什么 channel 与 agent 拆成两轴，而不是「channel 自带 agent」

传输（消息怎么到）与应答（这段对话怎么理解/回应）是两个正交的维度，而且
**channel 收到的消息无法识别对端是哪个 agent**——企微 aibot 协议里没有
「我是 OpenClaw」这样的字段。硬把 agent 塞进 channel，就是把一条传输和某个
具体运行时焊死，换一个运行时就得换一条 channel。拆分后每轴各加一个 addon。

### 为什么 channel 与 agent 互不依赖，由 thread 运行时绑定

谁是谁的 agent 是部署时的配置（数据），不是代码关系。把「OpenClaw 经企微
触达」写成 `agenthub_openclaw` 依赖 `agenthub_wecom`，就等于在代码里断言了
「OpenClaw 只能走企微」，而实际上 OpenClaw 换条 channel、或企微接别的 agent，
都不该改任何一边的代码。

### 为什么 thread 继承 mail.thread，而不是 plain 模型

会话天然是「聊天」：有消息、有角色、有附件、要实时推送、要在 Discuss 界面
里展示。`llm.thread` 已经用 `mail.thread` + `mail.message` 把这套做完了
（角色、`body_json`、流式原地更新、`to_store_format()` 推送）。agenthub 抄同一
个模型，白拿聊天 UI 和流式基础设施，不用重造。

### 为什么传输字段放 mail.message 上，而不是单开 agenthub.message / delivery 表

「这条消息说了什么」与「这条消息投递到哪了」是同一个逻辑对象的两面。拆成
两张表（内容表 + 投递表）就多一张表的同步与关联（正是 InfoHub 想避免的
拆分之痛）。`llm` 已经示范过在 `mail.message` 上 `_inherit` 加 `llm_role` /
`body_json`，agenthub 加自己的 `agenthub_*` 字段是同一条路。

### 为什么出站走 DB 而不是直接写 socket

WebSocket 连接活在 gevent worker 进程；发起消息的 Discuss/业务代码活在
HTTP/cron worker（另一进程）。内存态注册表跨不过进程边界，DB 是现成的跨进程
总线（Odoo `bus.bus` 同款）。代价是「轮询」带来一点投递延迟，换取进程解耦。

### 为什么关联用 agenthub_external_id + agenthub_reply_to_external_id，而不是 agent 直连 channel

channel 归一化时填好关联 id，agent 只消费这两个字段，就能在完全不知道
channel 实现的情况下把「提问」与「回包」配对。这是 channel/agent 解耦在
消息关联上的落点。

## 被否决的方案

| 方案 | 否决理由 |
|---|---|
| 一对一硬编码「Odoo↔企微↔OpenClaw」 | 新增传输或 agent 都要重写路由/落库/重试，无法沉淀为框架。 |
| agent 依赖 channel（`agenthub_openclaw` 依赖 `agenthub_wecom`） | 在代码里断言「OpenClaw 只能走企微」；且企微消息本无法识别对端 agent，反了。 |
| plain `agenthub.thread` + 独立 `agenthub.message` 表 | 弃用。会话就是聊天，`mail.thread` 白送 UI/流式/附件；内容与投递拆两张表徒增同步。 |
| 复用 `bus` 的 `WebsocketConnectionHandler` 直接跑 aibot | 该 handler 深度耦合 bus 通知协议（channel/subscribe/poll），不是通用 JSON 协议承载，改造不如自建连接循环。 |
| 独立 WS 进程（`websockets` 库）承载 aibot | 与 Odoo 解耦更彻底，但「在 Odoo 里做 addon」的诉求下多一个进程/端口/运维面；MVP 先用 gevent 承载，将来确需独立扩缩容再拆。 |
| agent 与 channel 合并成一个模型 | 无法表达两轴正交（见上），会把 `agent_type` 与 `channel_type` 搅成一维笛卡尔积。 |
| 用 `_component_match` 消歧 | 框架在 collection/model 之外无法消歧，会抛 `SeveralComponentError`。usage 后缀天然唯一。 |

## 后续扩展（不在本阶段，仅锚定方向）

- 新 channel：`agenthub_telegram` / `agenthub_web` 等，各加 `_inherit` 字段 +
  `selection_add` + `agenthub.channel.<type>` component。
- 新 agent：`agenthub_opencode`、`agenthub_llm`（包内部 `llm.agent`）、
  `agenthub_human` 等，各加 `agenthub.agent.<type>` component。
- `agenthub_discuss`：薄的入口 addon，把 `agenthub.thread` 接进 Discuss 聊天
  界面（`llm_discuss` 的 `llm.chat_client_action` 同款），core 保持 UI 无关。
- 路由规则模型：把「channel + peer pattern → 默认 agent」的自动绑定从
  thread 上显式 `agent_id` 中抽出来，作为可选的自动建会话层。
