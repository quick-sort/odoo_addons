agenthub
========

Odoo 与外部 AI Agent 运行时（OpenClaw 等）对话的**可扩展框架**。

它把「Odoo 与外部智能对话」拆成两轴：

* **channel（传输）** —— 消息从哪条线上进来、往哪条线出去。企微、Telegram、
  网页… 都是 channel 的一种。
* **agent（应答）** —— 一个「对话对象」是谁、怎么理解它的消息。OpenClaw、
  OpenCode、内部 ``llm.agent``、人工… 都是 agent 的一种。

两者正交且互不依赖：一条 channel 上跑的是谁，channel 不知道也不该知道；一个
agent 经哪条 channel 触达，agent 不关心。谁配谁，由 ``agenthub.thread`` 在
运行时绑定。

本 addon 只提供抽象（3 个模型 + 对 ``mail.message`` 的字段扩展 + 2 个 component
扩展点 + 路由），不含任何具体 channel 或 agent 实现。会话载体是 ``mail.thread``
（对齐 ``llm.thread``），入口复用 Discuss 聊天界面。

.. contents::

安装
----

``agenthub`` 依赖 component 框架，不依赖 ``llm``，也不绑定任何具体 channel /
agent。要真正接通，需要再装至少一个 channel 和至少一个 agent：

* ``agenthub_discuss`` —— Discuss 入站消息 → ``agenthub.publish`` outbox（推荐入口）。
* ``agenthub_wecom`` —— 企微智能机器人（aibot）WebSocket 服务端（已标记 legacy）。
* ``agenthub_openclaw`` —— OpenClaw 的对话语义（已标记 legacy）。

架构
----

::

    agenthub (core)
    ├── agenthub.channel   传输配置 (channel_type 置空, component 扩展)
    ├── agenthub.agent     外部 agent 注册 (runtime/service user/token)
    ├── agenthub.thread    会话 = channel + peer + agent (mail.thread)
    ├── agenthub.turn/command/delivery/publish
    └── mail.message       语义消息 + 长期归档
    relay (独立服务)       实时连接、路由、队列、record feed
    agenthub_discuss       Discuss 入站 → publish outbox

扩展一个 channel 或一个 agent，都只加一个独立 addon：

* channel addon：``_inherit`` 加字段 + ``selection_add`` 加 ``channel_type`` +
  ``agenthub.channel.<type>`` component。
* agent addon：``_inherit`` 加字段 + ``selection_add`` 加 ``agent_type`` +
  ``agenthub.agent.<type>`` component。

目标架构（>100 agent）把实时连接、路由和队列移到独立 relay；Odoo 只做配置、
Discuss UI、publish outbox、异步记录与归档。详见 ``docs/relay-v1.md`` 与
``docs/relay-message-envelope.md``。``agenthub_wecom`` 与 ``agenthub_openclaw``
为 legacy，保留给已有安装。

配置
----

通过 ``ir.config_parameter`` 配置 relay：

* ``agenthub.relay_url`` — relay 地址
* ``agenthub.relay_secret`` — publish outbox 的 HMAC 密钥
* ``agenthub.relay_recorder_token`` — recorder 拉取 record feed 的 token
* ``agenthub.relay_config_token`` — relay 拉取配置快照的 token
* ``agenthub.recorder_batch_limit`` — 单次拉取上限（默认 500）

设计文档
--------

详细设计见 ``docs/``（唯一事实来源）：

* ``docs/requirements.md`` —— 业务需求与边界
* ``docs/design.md`` —— 架构、模型、扩展点、被否决方案
* ``docs/acceptance.md`` —— 验收标准（QC 依据）
