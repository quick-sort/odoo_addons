=====================
Agent Hub Provisioner
=====================

在 Odoo 里管理 agent-box 容器的生命周期：创建、启动、停止、删除、状态同步
和日志查看。它是 agenthub 的控制面，不参与消息投递；消息仍然经 relay 传输。

本 addon 只提供模型、环境变量渲染、状态机和抽象 driver。真正控制宿主机的
能力由独立 driver addon 提供：

* ``agenthub_provisioner_docker`` —— 通过 Docker Engine API（unix socket 或
  TCP+TLS）控制。
* ``agenthub_provisioner_ssh`` —— 通过 SSH 在远端执行 ``docker`` 命令行。

安装
====

至少安装本 addon 和一个 driver addon：

.. code-block:: bash

   docker exec odoo odoo -c /etc/odoo/odoo.conf -d <db> \
       -i agenthub_provisioner,agenthub_provisioner_ssh \
       --stop-after-init --workers=0 --no-http

创建/重建动作通过 ``queue_job`` 异步执行。请在 ``odoo.conf`` 的
``[queue_job] channels`` 中给 ``root.agenthub`` 分配容量，例如：

.. code-block:: ini

   channels = root:2,root.agenthub:2

使用
====

1. 在 **Agent Hub → Provisioning → Hosts** 新建宿主机，选择 driver 并填连接参数。
2. 在 **Deployments** 新建部署，选择 agent、host、模式（relay / odoo_discuss）。
3. 填写 LLM profile（网关地址、密钥、模型）或直接留空由 ``extra_env`` 提供。
4. 点击 **Apply**。Odoo 渲染环境变量和容器 spec，由 driver 创建/启动容器。
5. 配置变化后再次 **Apply**；相同配置不会重建容器。

Relay token 由主密钥派生，不在数据库中保存明文。主密钥按优先级读取：

1. 环境变量 ``AGENTHUB_PROVISIONER_TOKEN_SECRET``；
2. ``ir.config_parameter`` 的 ``agenthub.provisioner.token_secret``。

两者都未配置时 Apply 会报错。

配置
====

* ``agenthub.provisioner.allowed_images`` —— 允许运行的镜像 glob，逗号分隔，
  默认 ``ghcr.io/quick-sort/agent-box:*``。
* ``agenthub.provisioner.token_secret`` —— relay token 主密钥（推荐用环境变量）。

安全
====

* 仅系统管理员可管理 host、deployment 与 LLM profile。
* Docker socket 等价于宿主机 root 权限；生产优先使用 SSH driver。
* 只接管带 ``agenthub.managed=true`` label 的容器，绝不修改用户自己的容器。
* 密钥字段仅系统管理员可见，UI/日志一律打码。

设计文档
========

详细设计见 ``docs/``（唯一事实来源）：

* ``docs/requirements.md`` —— 业务需求与边界
* ``docs/design.md`` —— 模型、component 接口、状态机、被否决方案
* ``docs/acceptance.md`` —— 验收标准（QC 依据）
