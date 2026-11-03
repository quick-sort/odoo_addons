===========================
Agent Hub Provisioner (SSH)
===========================

`agenthub_provisioner` 的 SSH driver：通过 SSH 登录远端主机，在远端执行
`docker` 命令行来控制 agent-box 容器。Odoo 容器不需要 docker socket，也不
需要 ssh/docker CLI，只需要 Python ``paramiko``。

安装
====

.. code-block:: bash

   docker exec odoo odoo -c /etc/odoo/odoo.conf -d <db> \
       -i agenthub_provisioner,agenthub_provisioner_ssh \
       --stop-after-init --workers=0 --no-http

配置
====

在 **Agent Hub → Provisioning → Hosts** 新建 host，``driver_type`` 选 ``SSH``：

* ``ssh_host`` / ``ssh_port`` / ``ssh_user`` —— 登录信息；
* ``ssh_private_key`` —— PEM 私钥内容（仅系统管理员可见）；
* ``ssh_known_hosts`` —— 目标主机公钥；默认严格校验 host key；
* ``remote_docker`` —— 远端 docker 命令，默认 ``docker``。

确保运行 Odoo 的容器能访问目标主机的 SSH 端口，并且远端用户有执行
``docker`` 的权限（通常属于 docker 组）。

行为
====

* 环境变量经 stdin 写入远端 ``/tmp`` 下的随机文件（0600），通过
  ``docker --env-file`` 使用，动作结束（成功或失败）立即删除。
* 命令全部由 argv 列表经 shell quoting 生成，不拼接未转义输入。
* 只操作带 ``agenthub.managed=true`` label 的容器；同名未托管容器报冲突。
* 相同配置 hash 重复 Apply 不重建；配置变化时先 stop/rm 旧容器再创建。

安全
====

* 默认严格校验 host key；关闭需显式配置，存在中间人风险。
* 私钥/口令仅系统管理员可见。
* 远端 docker 组等价 root；请使用最小权限账号与网络隔离。

设计文档
========

* ``docs/requirements.md``
* ``docs/design.md``
* ``docs/acceptance.md``
