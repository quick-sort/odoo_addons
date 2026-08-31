# Odoo 19 Odoobot / Discuss 架构研究

Status: research notes (2026-08-31)，来源代码 `/Users/rui/workspace/odoo`（19.0 分支）。
与 [DESIGN.md](DESIGN.md) 的关系：DESIGN.md 描述已实现（v1）的桥接模块；本文是
底层架构研究 + v2 方向（多轮上下文、流式）的深化设计。v1 已覆盖的部分（触发规则、
queue 模型、cron 唤醒）本文不重复，只补充其依赖的内核机制。

## 1. Odoobot 架构解剖

odoobot 是一个**极简的钩子 + 状态机**设计，核心只有两个挂载点，总代码量极小。

### 1.1 身份层：不是独立模型

Odoobot 就是 `base.partner_root`（XML-ID 引用的一个 `res.partner`，对应
`base.user_root`）。Bot 消息 = 以该 partner 为 author 的普通 `mail.message`。
前端对 bot **零特殊处理**——它就是一个普通 channel 成员。

推论：任何 partner 都可以扮演 bot。llm_discuss v1 已利用这一点（每个 assistant
一个 `discuss_user_id`），比共用 `partner_root` 干净。

### 1.2 逻辑层：`mail.bot` AbstractModel

文件：`addons/mail_bot/models/mail_bot.py`

- `_apply_logic(channel, values, command=None)`（mail_bot.py:14）— 入口，守卫过滤：
  - `values.get("author_id") == odoobot_id` → 跳过（防自回复循环）
  - `message_type != "comment" and not command` → 跳过（忽略系统消息）
  - 通过后调 `_get_answer(channel, body, values, command)`，有答案则逐条
    `channel.sudo().message_post(author_id=odoobot_id, ..., silent=True)`（mail_bot.py:31）
- `_get_answer()`（mail_bot.py:54）— 纯 Python 状态机。状态存
  `res.users.odoobot_state` 字段，流转：
  `onboarding_emoji → onboarding_command → onboarding_ping →
  onboarding_attachement → onboarding_canned → idle`
  每个状态匹配特定用户输入（emoji 检测、`/help` 命令、@mention、附件、
  canned response `::`），不匹配则进入 "repeat question" 分支（置
  `odoobot_failed`）。另有 idle 态的 easter eggs 和 help fallback。
  `_body_contains_emoji()`（mail_bot.py:196）是硬编码 Unicode 区间检测。

关键特性：**整个链路是同步的**，跑在用户发消息的同一个 HTTP 事务里。odoobot
靠预写答案（微秒级）才敢这么做——这正是 LLM bot 不能照抄的核心矛盾，
llm_discuss v1 的 queue + cron 异步化即为此而生。

### 1.3 挂载点：继承 `discuss.channel`

文件：`addons/mail_bot/models/discuss_channel.py`

```python
def execute_command_help(self, **kwargs):
    super().execute_command_help(**kwargs)
    self.env['mail.bot']._apply_logic(self, kwargs, command="help")

def _message_post_after_hook(self, message, msg_vals):        # :13
    self.env["mail.bot"]._apply_logic(self, msg_vals)
    return super()._message_post_after_hook(message, msg_vals)
```

即：**channel 里任何 message_post 完成后同步触发**。llm_discuss v1 复用的正是
这个 hook（`_message_post_after_hook`），架构与 mail_bot 完全同构。

注意：`mail.bot` 是 AbstractModel，理论上其他模块可以继承 `mail.bot` 覆写
`_get_answer` 来给 odoobot 加逻辑——但 llm_discuss 没这么做（也不该做：语义上
llm_discuss 是"新 bot"，不是"扩展 odoobot"）。

### 1.4 实时推送管线

`addons/mail/models/discuss/discuss_channel.py:936`：

```python
def _notify_thread(self, message, msg_vals=False, **kwargs):
    rdata = super()._notify_thread(message, msg_vals=msg_vals, **kwargs)
    payload = {"data": Store(bus_channel=self).add(message).get_result(), "id": self.id}
    ...
    self._bus_send("discuss.channel/new_message", payload)
```

链路：`message_post` → `_notify_thread` → `Store` 序列化消息 →
`_bus_send("discuss.channel/new_message")` → bus.websocket 推送 →
前端 Owl Store 更新。**只要后端 post 消息，Discuss UI 自动出现，前端零改动。**

`discuss.channel.message_post`（discuss_channel.py:1006）本身也值得注意：
- 非 notification 类型会更新 `last_interest_dt`
- `special_mentions` 里的 `everyone` 会展开为全部成员 partner_ids
- `partner_ids` 经 `_get_allowed_message_partner_ids`（:987）过滤——
  channel 类型按 `group_public_id` 过滤，chat 类型按 member 过滤。
  **这意味着 @bot mention 要生效，bot partner 必须是 channel 成员。**

## 2. Discuss 前端架构（简要）

- Owl 3 组件 + 自研 ORM 式 record 层：`Record` / `Store`
  （`addons/mail/static/src/core/common/record.js`、`thread_model.js`、
  `message_model.js` 等），`discuss.channel` 映射为 `Thread` record，
  消息/成员/persona（partner 与 guest 的统一抽象）都是 record。
- 一切增量更新来自 bus websocket 推送的 Store payload；record 层按
  model/id 自动合并。前端没有为 bot 预留任何扩展点，也不需要。
- 公开页面（`/chat/<token>` 等）走 `PublicPageController`
  （`addons/mail/controllers/discuss/public_page.py`），同一套 Store 机制，
  guest 也经 `mail.guest` persona 进来——对 bot 而言 guest 消息与用户消息
  无差别，都会过 `_message_post_after_hook`。

## 3. v2 方向之一：多轮上下文（DESIGN.md §3/§8 遗留项）

v1 把触发消息的 body 作为 query 喂给 `llm.assistant.invoke()`，每次调用开新
`llm.thread`，assistant 看不到频道历史。v2 的核心问题是：discuss.channel 的
消息历史如何进入 LLM 上下文。

### 3.1 方案对比

| 方案 | 做法 | 优点 | 缺点 |
|---|---|---|---|
| A. 双写 | 用户消息同时 post 到 channel 和 llm.thread | 简单直接 | channel 是 UI 真相源，双写必然漂移（编辑/删除/删不同步） |
| B. channel 即历史 | `llm.thread` 扩展：绑定的 thread 直接把 discuss.channel 消息当作自己的历史（override `get_llm_messages()` 按 channel 查询） | 单一真相源，无同步问题；`llm.thread` 已继承 `mail.thread` 且消息查询按 `model/res_id`，机制天然兼容 | 需要处理 role 映射（bot 消息 → assistant role，人类消息 → user role）；thread 独立 UI 与 channel 消息会混在一起，需注意隔离 |
| C. 每轮重放 | 每次触发时把 channel 最近 N 条消息拼成 messages 传给 LLM | 无 schema 改动 | 每轮重放，token 浪费；llm.thread 里的 assistant 内部推理（tool 调用链）无法保留 |

**推荐 B**。依据（来自 `llm_assistant/models/llm_thread.py` 的实现事实）：
- `llm.thread.generate_messages()` 的上下文全部来自 `get_llm_messages()`
  （llm_thread.py:351）：按 `model='llm.thread', res_id=thread.id,
  llm_role != False, is_error = False` 查 `mail.message`。
  该方法是普通 model method，可在 llm_discuss 里对绑定了 channel 的 thread
  override 为按 channel 查询。
- role 映射规则：`author_id == bot partner` → `assistant`，其余 → `user`；
  写入时需同步写 `llm_role`（`message_post` 支持 `llm_role` 参数，
  见 `_handle_streaming_response` 中的用法）。
- 前置验证点（实现前必须确认）：
  1. `mail.message.message_post` 覆写链中 `llm_role` 的写入路径
     （`llm_thread` 基模块的行为）；
  2. `_process_llm_body` 对 channel 消息 body（HTML）的反向提取——
     LLM 上下文需要纯文本，channel 消息是 HTML，需要 html2text 或
     改用 `body_json`/纯文本通道；
  3. channel 消息的 `model/res_id` 指向 `discuss.channel`，而 thread 查询
     域是 `model='llm.thread'`——override 时以 channel 为查询目标即可，
     但 `_thread_to_store` / 独立 chat UI 不要把 channel 消息误收进 thread 视图。

### 3.2 与 v1 的衔接

v1 的 queue row 已存 `channel_id` + `source message`。v2 只需把
`invoke(query)` 换成「ensure bound thread → 直接调 `thread.generate()`」，
并让绑定 thread 的 `get_llm_messages()` 走 channel 查询。绑定关系可以复用
v1 已传入的 `thread_vals={"model": "discuss.channel", "res_id": channel.id}`
（即 `llm.thread` 的 generic res_model 指向 channel），再加一个显式
`discuss_channel_id` 字段做唯一绑定与 role 映射锚点。

## 4. v2 方向之二：流式呈现（DESIGN.md §8 遗留项）

Discuss 没有原生 SSE 通道给消息体。两个选项：

- **(a) 占位消息 + 完成时更新**：触发后先 post 一条 "…"（或 "Thinking…"）
  占位消息；生成完成后更新其 body 并经 bus 推送更新事件。前端需要一个
  小 patch：`discuss.channel` 侧新增自定义 bus 事件（如
  `discuss.channel/llm_chunk`），前端 `thread_model` patch 监听并更新
  消息 record。工作量小，体感是"整段出现"或"分段出现"。
- **(b) 完全流式**：`llm.thread.generate()` 本就是 generator（yield
  `message_chunk` 事件，见 `_handle_streaming_response`），后端把每个
  chunk 转 bus 事件推送。体感最好，但 bus 每秒推送量需要节流
  （如 100~250ms 聚合一次），且要处理订阅者离线时的最终一致
  （推送结束事件后重拉消息）。

**推荐先做 (a)**：复用 `generate()` 的 yield 事件流，仅在
`message_update`（或聚合节流后的 chunk）时转发 bus 事件；
( a ) 验证通过后再演进到 (b)，前端 patch 是同一套，只是事件粒度不同。

后端节流点：queue job 内消费 generator，对 `message_chunk` 事件做
时间窗聚合（如 ≥200ms 或 ≥16 token 才 `_bus_send` 一次），
避免打爆 websocket。

## 5. 触发与安全补充（相对 DESIGN.md §5/§7 的新发现）

- **mention 生效的前提是 bot 是成员**：`_get_allowed_message_partner_ids`
  （discuss_channel.py:987）会把不在成员里的 mention 过滤掉，所以
  `discuss_trigger_mode = mention` 依赖 v1 的"绑定 assistant 时自动拉 bot
  入成员"行为——若 channel 创建早于绑定，需确保补拉成员。
- **`everyone` mention 不会触发 bot 的 mention 规则**：`special_mentions`
  中的 `everyone` 展开为全部成员 partner_ids（discuss_channel.py:1010），
  因此 bot partner 会出现在 `partner_ids` 里——如果不想让 @everyone 触发
  bot，`_llm_discuss_should_trigger` 需要把 `everyone` 从 special_mentions
  里排除后再判断。
- **guest 消息同样过 hook**：公开页面（/chat/<token>）的 guest 消息会走
  `_message_post_after_hook`。llm_discuss 的触发条件目前不区分
  author 类型，若 bot 所在 channel 可能被 guest 访问（邀请链接），
  应在 `_llm_discuss_should_trigger` 里显式决策（放行或拒绝 guest）。
