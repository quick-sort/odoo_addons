agenthub_openclaw
=================

`agenthub` 的第一个 **agent** 实现：OpenClaw 的对话语义。

它只负责「和 OpenClaw 对话该怎么理解」——流式回包累积、``<think>`` 块与正文
分离、用关联 id 把回包对应回原提问。它**不实现传输**：消息怎么送到 OpenClaw、
回包怎么回来，是 core 路由 + 具体 channel 的事。

.. contents::

安装
----

依赖：``agenthub``。

要真正接通 OpenClaw，还需要一个 channel（如 ``agenthub_wecom``）。两者互不
依赖，绑定方式是运行时配置：

1. 建一条 ``agenthub.channel``（channel_type=wecom），配好 ``bot_id``/``secret``。
2. 建一条 ``agenthub.agent``（agent_type=openclaw）。
3. 建一条 ``agenthub.thread``，``channel_id`` 指上面的 channel、``peer_ref``
   填 bot_id、``agent_id`` 指上面的 agent。

这样「这条企微 bot 的对话由 OpenClaw 应答」就成立了。

架构
----

::

    agenthub_openclaw (agent 语义)
      ├── 流式回包累积 (stream.id + finish)
      ├── <think> 剥离 + markdown 保留
      └── agenthub_reply_to_external_id 关联回原提问

    (传输交给 agenthub_wecom + agenthub core 路由)

设计文档
--------

* ``docs/requirements.md`` —— 业务需求与边界
* ``docs/design.md`` —— 对话语义、流式累积、解耦边界
* ``docs/acceptance.md`` —— 验收标准（QC 依据）
