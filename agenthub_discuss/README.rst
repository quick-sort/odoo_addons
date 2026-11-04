agenthub_discuss
================

把绑定到 ``agenthub.thread`` 的 Discuss 用户消息写入 ``agenthub.publish``
outbox，由 relay 转发给对应的外部 agent。

安装
----

依赖 ``agenthub``。安装后，用户在与 agent service user 的 Discuss 会话里发消息，
``discuss.channel._message_post_after_hook`` 会生成 ``message.created`` 事件：

* ``route.thread_key = discuss.channel:<id>``
* ``meta.origin = odoo``
* ``meta.origin_record_id = mail.message,<id>``

recorder 收到回包时按 ``origin_record_id`` 跳过用户原始消息，只投影 agent 回复。
agent 自己发的消息（author 为 service user partner）和 OdooBot 消息不会被回灌。

设计文档见 ``docs/``。
