# LLM Discuss — 系统设计

## 定位：llm 桥接 discuss_agent

`llm_discuss` 是 **llm.agent 桥接 `discuss_agent` 接口的 addon**。它不再自己实现
普通 Discuss 的触发与队列，而是让 `llm.agent` 通过 `discuss_agent` 的统一接口接入：

- `discuss_agent` core 定义多态 responder（`discuss.agent`）、统一 pending 载体
  （`discuss.reply.job`）、统一触发（`_discuss_dispatch`）与执行契约
  （`_discuss_execute`）。
- `llm_discuss` 实现 llm 这一种 responder：注册 `agent_type="llm"`、给 `llm.agent`
  加 `_discuss_execute` 协议方法、把 `llm.agent` 的 Discuss 配置同步成 `discuss.agent`
  桥接记录、并提供消费 `discuss.reply.job` 的 worker cron。

依赖：`base, mail, mail_bot, llm, discuss_agent`。**更新/安装时 `discuss_agent` 与
`llm_discuss` 都要进 `-u` 列表**（前者是接口 core，后者是桥接）。

## 数据流（普通 Discuss 触发）

```
discuss.channel._message_post_after_hook
  ├─ llm_discuss 的 hook：仅处理 OdooBot 接管（见下），其余 super()
  └─ discuss_agent 的 hook → discuss.agent._discuss_dispatch
       遍历 discuss.agent（含 agent_type=llm 的桥接记录）
       → channel._discuss_should_trigger（@mention / 私聊 / both）
       → channel._discuss_user_can_use_agent（llm_discuss override，保留 llm 授权）
       → agent._discuss_enqueue_reply 入 discuss.reply.job（固化 source_user + reply_partner）
       → agent._discuss_after_enqueue()  ──▶ llm_discuss override：_trigger worker cron

cron ir_cron_process_discuss_reply_job
  → discuss.reply.job._discuss_cron_process_pending（llm_discuss 提供）
  → _claim_pending(agent_types=["llm"])      # 只认领 llm 的 job
  → _execution_user_and_company()            # source_user，fail-closed
  → agent._discuss_execute()                 # 分派到 llm.agent._discuss_execute
       → with_user(execution_user)._invoke_with_background(...)
  → job._complete(result)                    # 回帖（作者=reply_partner）+ 置 done
```

## 桥接机制

`llm.agent` 的 Discuss 参与，通过一条 `discuss.agent`（`agent_type=llm`、
`res_model=llm.agent`、`res_id=<agent>`）承载。三个桥接动作：

1. **字段同步**：`llm.agent` 的 `discuss_user_id` / `discuss_enabled` /
   `discuss_trigger_mode` 仍是用户在 `llm.agent` 表单上的配置入口；`create`/`write`
   触发 `_discuss_sync_agent()`，自动 upsert/删除对应的 `discuss.agent`
   （`discuss_agent_id` 反向关联）。单一真相源在 `llm.agent`，桥接记录是 dispatcher
   读取的对象。
2. **执行协议**：`llm.agent._discuss_execute(execution_user, company, query, ...)`
   转调 `_invoke_with_background`，返回 `{result_html/result/thread_id}` 或
   `{error}`——discuss_agent 的同步执行形态。
3. **授权收敛**：`discuss_channel._discuss_user_can_use_agent` 对 `agent_type=llm`
   委托回 `llm.agent._get_allowed_agents_for_user`，不回退成"所有内部用户可用所有
   agent"。

## 触发与 OdooBot 接管

普通触发（@mention / 私聊 / both）在 `discuss_agent` core 完成，`llm_discuss` 只
override `_discuss_user_can_use_agent` 收紧授权。

OdooBot 接管仍由 `llm_discuss` 自己负责（**尚未迁移到 discuss_agent**）：
`_llm_discuss_odoobot_takeover_agent()` 在 `super()` **之前**捕获 eligibility（因为
最后一条 onboarding 消息把 `odoobot_state` 置 `idle`，该消息必须只收到原生教程收尾，
不能成为 LLM 首答）。接管需**同时**满足：

- 一个 active agent 启用了 **Use for OdooBot Private Chat**；
- 发送者是允许使用该 agent 的内部用户；
- 发送者 `odoobot_state` 为 `idle` 或 `disabled`；
- channel 是只含该用户与 `base.partner_root` 的真 1:1 chat；
- 消息是用户 comment。

继承 `mail.bot._apply_logic()` 仅在上述条件成立时抑制原生 canned 回复；onboarding
各态、`start the tour` 重启、`/help` 仍交 core `mail_bot`。命中后走
`_llm_discuss_dispatch_odoobot` → `llm.discuss.reply.queue`（旧队列）→ 旧 cron。

**注意**：同一 `llm.agent` 若同时 `odoobot_enabled=True` 与 `discuss_enabled=True`，
OdooBot 私聊会撞双路径（旧队列 + discuss.reply.job）。约定：OdooBot 接管的 agent
不设 `discuss_enabled`。

## 队列

两条队列并存，触发条件不同、不重叠：

| 队列 | 服务对象 | worker | 触发 |
|---|---|---|---|
| `discuss.reply.job`（discuss_agent） | 普通 Discuss 触发 | `llm_discuss` 的 `_discuss_cron_process_pending` | discuss_agent dispatch |
| `llm.discuss.reply.queue`（llm_discuss） | OdooBot 接管 | 旧 `_cron_process_pending` | `_llm_discuss_dispatch_odoobot` |

`discuss.reply.job` 是精简版接口载体（状态机 + `_claim_pending(agent_types)` +
`_complete`/`_complete_error`）。`llm.discuss.reply.queue` 保留完整的 fencing /
typing / 超时重放禁用 / GC 细节，供 OdooBot 接管使用。

## 执行身份与 sudo 边界

原则与收敛前一致（见 discuss_agent core 的 design.md）：

- **执行身份 = source_user**：`discuss.reply.job` 入队时固化 `source_user_id` /
  `source_company_id`，worker 用 `_execution_user_and_company()` fail-closed 解析，
  以 `with_user(source_user)` 绑定 agent；隐藏 `llm.thread`、消息、记录读取、工具都
  走发送者 ACL/记录规则/公司规则。
- **回复人格 ≠ 执行身份**：`reply_partner_id` 独立持久化，回帖用窄
  `channel.sudo().message_post(author_id=reply_partner)`；sudo 只用于发帖，不传给工具。
- provider/model 凭据经窄 sudo 读取；公开 `invoke()` 不收任意执行用户/系统背景，
  Discuss 走 `_invoke_with_background`。

## 尚未迁入 discuss_agent 的能力（收敛阶段回退，待迁）

以下能力原先在 `llm_discuss` 本地队列里，收敛到 `discuss_agent` 后普通 Discuss 触发
暂不具备，仅在 OdooBot 接管路径仍生效。迁入目标在 `discuss_agent` core：

1. **页面上下文**（`page_context`）：前端 patch 捕获的 `{res_model, res_id, ...}`
   快照，`discuss.reply.job` 尚未有对应字段，`_discuss_execute` 的 `background`
   暂为空。需在 `discuss.reply.job` 加 `page_context`、dispatch 捕获、worker 转成
   `background` 传给协议方法。
2. **typing 指示**：`discuss.reply.job` 尚无 `_notify_typing` 驱动，回复期间无原生
   "正在输入"。
3. **入方向附件**：`_discuss_execute` 尚未透传 `attachment_ids`；桥接协议需加该
   参数并下传 `_invoke_with_background`。
4. **fencing / 超时重放禁用 / GC**：`discuss.reply.job` 目前是精简状态机，未实现
   `_lock_owned_claim` / `_expire_stale_jobs` / `_gc_processed_jobs`。

## 附件支持（入方向，仅 OdooBot 路径生效）

`llm` 核心已具备多模态输入（`generate(attachment_ids=...)` → provider adapter 组装）。
`llm_discuss` 旧队列的 `_invoke_with_background(..., attachment_ids=...)` 透传链仍只
服务 OdooBot 接管；普通 Discuss 待上述「待迁入 #3」落地后恢复。判定沿用核心：
图片/PDF 需多模态模型，文本恒可用，视频/Office/音频不支持。附件 `datas` 全程在
execution principal 身份下读，读不到 fail closed，不升级 sudo。

## agent 可用性与单例

`discuss_channel._discuss_user_can_use_agent` 对 `agent_type=llm` 委托回
`_get_allowed_agents_for_user`，尊重 `is_public` 与 `allowed_group_ids`。OdooBot 接管
对每个发送者走同样规则。`odoobot_enabled` 由隐藏可空 key + DB 唯一约束支撑，并发写
也无法配置两个接管 agent。`discuss.reply.job` 对 `base.group_user` 可读写（供外部
JSON-RPC 运行时轮询），`discuss.agent` 对 `base.group_user` 可管理。

## 数据模型

`discuss_agent` core（见 `discuss_agent/docs/design.md`）提供：

- `discuss.agent`：多态 responder（`agent_type` / `res_model` / `res_id` +
  `discuss_user_id` / `discuss_enabled` / `discuss_trigger_mode`）。
- `discuss.reply.job`：统一 pending 载体（`agent_id` / `channel_id` / `message_id` /
  `reply_partner_id` / `source_user_id` / `source_company_id` / `state` /
  `claim_token` / `attempt_count` / `error_message`）。

`llm_discuss` 增量：

| 模型 | 增量 |
|---|---|
| `llm.agent` | `discuss_user_id`、`discuss_enabled`、`discuss_trigger_mode`、`odoobot_enabled`、`odoobot_unique_key`、`discuss_agent_id` |
| `discuss.agent` | `agent_type` selection_add `llm`；`_discuss_after_enqueue` |
| `discuss.reply.job` | `_discuss_cron_process_pending` / `_discuss_process_one` |
| `discuss.channel` | `_discuss_user_can_use_agent`（llm 授权）、OdooBot 接管 |
| `mail.bot` | `_apply_logic` 抑制原生 canned 回复 |
| `llm.discuss.reply.queue` | 旧队列（OdooBot 接管专用，含 fencing / typing / 附件透传） |

## 被否决的方案

| 方案 | 否决理由 |
|---|---|
| 出方向图片生成（image_generation 出图回帖） | base `_generate_response` 是 stub，需 provider 侧先实现；与入方向正交。 |
| 把附件读成文本塞进 `query` / `background` | 图片无法文本化、PDF 需解析，且绕过核心既有格式化与校验。 |
| 在 `llm_discuss` 里重新实现图片 → base64 → content block | 重复造轮子；核心 `_get_*_attachments` + adapter 已按 provider 语义正确组装。 |
| 公开 `invoke()` 直接收 `attachment_ids` | RPC 面扩大，违背「公开入口不收任意上下文」；只走 `_invoke_with_background`。 |
| 继续让 `llm_discuss` 自己 dispatch 普通 Discuss | 与 `discuss_agent` 双触发、双队列，同 agent 可重复回复；收敛为桥接消除双路径。 |
| 一次性把 OdooBot 接管也迁入 `discuss_agent` | 涉及 `base.partner_root` 人格 + `odoobot_state` 判定，风险高；先保留本地队列，后续单独迁。 |

## 扩展点

1. **多轮上下文**（v2）：把绑定 channel 的隐藏线程 `get_llm_messages()` override 为
   按 channel 查询，role 映射 bot→assistant、人→user。
2. **流式呈现**（v2）：先「占位消息 + 完成更新」复用 `generate()` 的 yield 事件经
   bus 转发，再演进到完全流式。
3. **出方向图片**：image_generation 接入后，把 assistant 消息附件复制到 channel 回帖。
4. **音频 / Office→PDF 输入**：核心已有分支，放开 gate 或接 extractor。
5. **OdooBot 接管迁入 discuss_agent**：把 `base.partner_root` 人格 + `odoobot_state`
   判定抽象成 discuss_agent 的一种触发，弃用 `llm.discuss.reply.queue`。
6. **待迁入能力补齐**：页面上下文、typing、附件透传、fencing/GC 迁入
   `discuss_agent` core。

## 布局

```
llm_discuss/
├── models/
│   ├── llm_agent.py               # discuss 配置字段 + 同步 discuss.agent + 协议方法
│   ├── discuss_agent.py           # agent_type=llm + _discuss_after_enqueue
│   ├── discuss_channel.py         # llm 授权 override + OdooBot 接管
│   ├── discuss_reply_job.py       # 消费 discuss.reply.job 的 worker
│   ├── mail_bot.py                # 抑制原生 canned 回复
│   └── llm_discuss_reply_queue.py # 旧队列（OdooBot 接管专用）
├── static/src/                    # 启动器 + 页面上下文 patch
├── data/                          # cron（旧队列 + discuss.reply.job worker）
├── security/                      # ACL
└── views/                         # llm.agent 表单扩展
```
