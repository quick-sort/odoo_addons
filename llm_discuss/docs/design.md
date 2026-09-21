# LLM Discuss — 系统设计

## 总体形态

用户可见的对话始终是原生 `discuss.channel`。本模块**不渲染**平行 LLM 聊天 UI，
**不修改** Odoo core，只在 `discuss.channel` 的 `_message_post_after_hook()` 上挂
桥接，把命中触发条件的消息异步交给 `llm.agent`，再把结果回帖到 channel。

```
Composer / ChatWindow
    -> discuss.channel.message_post()
    -> llm.discuss.reply.queue（入队，快照执行身份）
    -> llm.agent（stream=False）
    -> discuss.channel.message_post(回复人格)
    -> discuss.channel/new_message bus -> Discuss / ChatWindow
```

专用 agent 用 systray 启动器走 `mail.store.openChat({ userId: botUserId })`，由
Odoo 创建/复用规范 1:1 channel 并选择正确 UI。OdooBot 接管则复用
`base.partner_root` 人格，不替换任何 core 记录。

## 触发与 OdooBot 接管

`discuss.channel._message_post_after_hook()` 评估启用中的专用 bot。触发模式：
私聊、显式 `@mention`、或两者（`discuss_trigger_mode`）。bot 自身消息与非 comment
消息被忽略。

OdooBot 接管的 eligibility 在 `super()` **之前**捕获——因为最后一条 onboarding
消息会把用户 `odoobot_state` 从 `onboarding_canned` 置为 `idle`，该消息必须只收到
Odoo 原生教程收尾，而不是重复的 LLM 答案。接管需**同时**满足：

- 一个 active agent 启用了 **Use for OdooBot Private Chat**；
- 发送者是允许使用该 agent 的内部用户；
- 发送者 `odoobot_state` 为 `idle` 或 `disabled`；
- channel 是只含该用户与 `base.partner_root` 的真 1:1 chat；
- 消息是用户 comment。

继承 `mail.bot._apply_logic()` 仅在上述条件成立时抑制原生 idle/disabled 的
canned 回复；onboarding 各态、`start the tour` 重启、`/help` 命令仍交给 core
`mail_bot`。

## 队列与栅栏

一条命中的消息按 `(agent, source message)` 各建一行 `llm.discuss.reply.queue`。
`reply_partner_id` 独立持久化可见作者/typing 人格，与执行用户解耦。唯一约束
`UNIQUE(agent_id, message_id)` 包在 savepoint 里，并发重复入队不会中断用户消息
事务。

worker：

1. `FOR UPDATE SKIP LOCKED` 认领一行 pending；
2. 分配随机 fencing token 并提交认领；
3. 以 `reply_partner_id` 发布原生 typing；
4. 以 `stream=False` 调用 agent；
5. 锁行、校验 fencing token；
6. 以持久化的回复人格 post 一条完整消息并标记 done；
7. 提交状态后，仅当该 persona 无其他活动 job 时清除 typing。

超时 job 被 fence 并标记 failed；**不自动重放**（工具可能有外部/非幂等副作用）。

## 执行身份与 sudo 边界

内部用户：队列在 post 时持久化发送者、活跃公司、不可变的 `source_user` 执行模式，
随后以 `agent.with_user(source_user).with_company(source_company)` 绑定 agent。
隐藏 `llm.thread`、其消息、相关记录读取、所有工具都走发送者 ACL/记录规则/公司规则；
隐藏线程 owner 即该执行用户。`reply_partner_id` 不参与授权——尤其显示
`base.partner_root` 并不授予 root 权限。

provider/model 凭据经窄 sudo 读取；最终回复用窄
`channel.sudo().message_post(author_id=reply_partner)`（cron 须以他人人格发帖）。
两处 sudo recordset 都不传给工具。

公开 `llm.agent.invoke()` 既不接受任意执行用户，也不接受 system-role 背景；
Discuss 走私有服务端入口（`_invoke_with_background`），且先校验 agent 可用性。

网站访客无内部源用户，Live Chat 桥（`llm_discuss_livechat`）持久化
`assistant_user` 模式，回退到 agent 的专用低权限 bot 用户，**永不 sudo**。
service-user 模式在非 Live Chat channel 会被拒绝。若源用户在处理前被删/停用/
失去内部身份，job **fail closed**，不切换执行主体。

## 页面上下文

`/mail/message/post` 之前，`Store.doMessagePost()` 的 patch 检查 channel 是否含
允许的专用 bot 或允许接管 agent 的 OdooBot 人格，然后捕获 Action Controller：

```json
{"version": 1, "res_model": "sale.order", "res_id": 42, "view_type": "form", "action_id": 123}
```

快照放进 `context.llm_discuss_page_context`（不是受限的 `post_data`）。每次发送
都捕获，悬浮窗跟随页面变化。非 form 视图省略 `res_id`。

服务端在入队时校验 model/id/view type/读权限；worker 在最终执行身份下再校验一次。
只有元数据 + `display_name` 进入 LLM 背景；JSON 标记为不可信引用数据，尖括号转义。

## 非流式生成与原生等待

Discuss 对每一轮（含 tool 调用后续轮）传 `stream=False`。最终 agent 消息即 channel
回复；错误与 tool 消息不会被误当答案。队列用回复人格 channel 成员的
`_notify_typing(True/False)` 驱动原生 typing，不产生临时「Thinking…」消息。

## agent 可用性与单例

专用启动器与普通 channel 都尊重 `is_public` 与 `allowed_group_ids`；OdooBot 接管
对每个发送者走同样的规则。前端只拿到安全的 bot/user/partner id，provider 详情与
凭据不暴露。`odoobot_enabled` 由一个隐藏的、带 DB 唯一约束的可空 key 支撑，并发
写也无法配置两个接管 agent。队列行仅 `llm.group_llm_manager` 可读，保留 7 天后由
cron 清理。

## 数据模型

`llm.discuss.reply.queue`：

| 字段 | 说明 |
|---|---|
| `agent_id` / `channel_id` / `message_id` | 触发三元组（message 为源消息） |
| `reply_partner_id` | 回复人格 / typing 人格（与执行用户解耦） |
| `source_user_id` / `source_company_id` | 业务数据与工具的执行身份 |
| `execution_mode` | `source_user` / `assistant_user`（后者仅 Live Chat 访客） |
| `page_context` | 入队时校验过的页面元数据快照 |
| `attachment_ids` | **入方向附件快照**（入队时捕获，执行期不可变） |
| `llm_thread_id` | 生成用隐藏线程 |
| `state` / `attempt_count` / `claim_token` / `error_message` | 栅栏队列状态 |

`llm.agent`（`_inherit` 增量字段）：`discuss_user_id`、`discuss_enabled`、
`discuss_trigger_mode`、`odoobot_enabled`、`odoobot_unique_key`。

## 附件支持（入方向）

核心判断：`llm` 核心**已具备**多模态输入——`llm.thread.generate(attachment_ids=...)`
→ `mail.message._get_image_attachments()` 等 → provider adapter 组装 image /
document / text content block；并带 `_get_unsupported_attachments` 兜底校验。缺的
只是 `llm_discuss` 这座桥没把附件接进去。

```
Discuss 消息 message.attachment_ids
   │  ① dispatch 时校验 + 入队快照
   ▼
llm.discuss.reply.queue.attachment_ids
   │  ② _invoke_with_background(attachment_ids=...)
   ▼
llm.thread.generate(attachment_ids=...)   ← 核心既有能力
   │  ③ provider adapter 多模态格式化
   ▼
assistant message（文本回帖到 channel）
```

1. **入队捕获**：`_llm_discuss_enqueue_reply` 读 `message.attachment_ids`，存队列
   `attachment_ids`（与 `page_context` 同款「入队即快照」）。
2. **执行透传**：`_process_one` 调
   `_invoke_with_background(..., attachment_ids=job.attachment_ids.ids)`。
3. **核心格式化**：`generate` 内部已做「user message 挂附件 + 兜底校验 + adapter
   多模态组装」，桥接层不重复。

### 核心 `llm` 的最小改动

`generate` 已支持 `attachment_ids`，但 invoke 链没透传。给以下签名加可选
`attachment_ids=None`，逐层下传至 `thread.generate(attachment_ids=...)`：

- `_invoke_with_background(..., attachment_ids=None)`
- `_invoke(..., attachment_ids=None)`
- `_run_in_thread(..., attachment_ids=None)`

公开 `invoke()`（RPC 可达）**不**新增该参数——附件透传只走受信服务端入口
`_invoke_with_background`，与「invoke 不接受任意执行用户/系统背景」一致。

### 不支持附件的反馈

核心 `generate` 对不支持附件是「标记 `is_error` + 在**隐藏线程**贴提示」，Discuss
用户看不到。因此校验前移：入队前用 agent 的 `provider_id.service` +
`model_id.supports_image_input` 调 `message._get_unsupported_attachments(...)`；
有 unsupported → 在 channel 贴原生提示（文件名 + 原因），并从透传集合剔除；
其余照常生成。判定沿用核心：图片/PDF 需多模态模型，文本文件恒可用，视频/Office/
音频不支持。（Discuss 每条消息独立隐藏线程，无「中途换模型」场景，入队前校验与
`generate` 内二次兜底不冲突。）

### 附件安全

附件 `datas` 读取全程在 execution principal 身份下，禁用 sudo。Live Chat 访客
附件的可读性取决于 bot 是否对 `discuss.channel` 附件有读权；读不到 → fail closed
（跳过 + 提示），不升级 sudo、不切换主体。

## 被否决的方案

| 方案 | 否决理由 |
|---|---|
| 出方向图片生成（image_generation 出图回帖） | base `_generate_response` 是 stub，需 provider 侧先实现；与入方向正交，本次裁剪，留作扩展点。 |
| 把附件读成文本塞进 `query` / `background` | 图片无法文本化、PDF 需解析，且绕过核心既有格式化与校验。 |
| 在 `llm_discuss` 里重新实现图片 → base64 → content block | 重复造轮子；核心 `_get_*_attachments` + adapter 已按 provider 语义正确组装。 |
| 公开 `invoke()` 直接收 `attachment_ids` | RPC 面扩大，违背「公开入口不收任意上下文」；只走 `_invoke_with_background`。 |
| 出方向直接复用隐藏线程附件回帖 | 附件归属仍是隐藏线程消息，channel 成员可能读不到，产生孤儿引用。 |

## 扩展点

1. **多轮上下文**（v2）：把绑定 channel 的隐藏线程 `get_llm_messages()` override
   为按 channel 查询，role 映射 bot→assistant、人→user（单一真相源，无双写漂移）。
2. **流式呈现**（v2）：先做「占位消息 + 完成更新」复用 `generate()` 的 yield 事件，
   经 bus 转发；验证后再演进到完全流式（后端按时间窗聚合 chunk 防打爆 websocket）。
3. **出方向图片**：待 image_generation 接入后，把最终 assistant 消息的附件复制到
   channel 回帖（复制/重归属，不与隐藏线程共享归属）。
4. **音频输入**：核心 `mail.message` 已有 `_get_audio_attachments` 与 adapter 分支，
   放开 `_get_unsupported_attachments` 的 gate 即可。
5. **Office → PDF**：将来接 `llm_knowledge` extractor 或独立转换工具，再透传 PDF。

## 布局

```
llm_discuss/
├── models/
│   ├── llm_agent.py               # discuss 增量字段 + bot 用户 + 入队
│   ├── discuss_channel.py         # 触发规则 / OdooBot 接管
│   ├── mail_bot.py                # 抑制原生 canned 回复
│   └── llm_discuss_reply_queue.py # 栅栏队列 + 执行身份 + 附件透传
├── static/src/                    # 启动器 + 页面上下文 patch
├── data/                          # cron
├── security/                      # ACL
└── views/                         # llm.agent 表单扩展
```
