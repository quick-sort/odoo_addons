agenthub_wecom
==============

`agenthub` 的第一个 **channel** 实现：企业微信智能机器人（aibot）WebSocket
服务端。

外部 AI Agent 运行时（OpenClaw、OpenCode 等）装上各自的企微插件，把
``websocketUrl`` 指到 Odoo，配上 ``bot_id + secret``，就能连进来收发消息。

本 addon 只做**传输**：收发帧、管连接、归一化成 ``mail.message``。对端是
哪个 agent 它不关心、也不该关心——channel 只认 ``bot_id``。

.. contents::

安装
----

依赖：``agenthub``。

WebSocket 只跑在 Odoo 的 **gevent worker**（8072 端口），需要 Odoo 以
``--gevent-port`` 起一个 evented worker。OpenClaw 侧配置：:

    channels.wecom.websocketUrl = ws://<odoo-host>:8072/wecom/aibot/ws
    channels.wecom.botId        = <bot_id>
    channels.wecom.secret       = <secret>

在 Odoo 里建一条 ``agenthub.channel``（channel_type=wecom），填相同的
``bot_id`` / ``secret``。

配置
----

* ``bot_id``：企微机器人 ID，与对端插件一致。
* ``secret``：机器人 secret，与对端插件一致。

架构
----

::

    外部 agent 运行时 ──(aibot WebSocket)──> agenthub_wecom
                                              │  归一化成 mail.message
                                              ▼
                                          agenthub core 路由

协议要点：subscribe 认证、ping 心跳、respond/send 的 req_id 精确 ACK、
多连接按 bot_id 区分 + 同 bot_id 互踢 + 跨进程下发走 DB。

设计文档
--------

* ``docs/requirements.md`` —— 业务需求与边界
* ``docs/design.md`` —— aibot 协议、连接生命周期、多连接处理
* ``docs/acceptance.md`` —— 验收标准（QC 依据）
