==============================
Agent Hub Provisioner (Docker)
==============================

`agenthub_provisioner` 的 Docker driver：通过 Docker Engine API 控制 agent-box
容器。支持本地 unix socket 和 TCP+TLS 端点。

安装
====

.. code-block:: bash

   docker exec odoo odoo -c /etc/odoo/odoo.conf -d <db> \
       -i agenthub_provisioner,agenthub_provisioner_docker \
       --stop-after-init --workers=0 --no-http

需要在 Odoo 镜像中安装 Python ``docker`` 包（manifest 的
``external_dependencies``）。

连接方式
========

**Unix socket（仅限受信单机）**

把宿主机的 Docker socket 挂进 Odoo 容器：

.. code-block:: yaml

   volumes:
     - /var/run/docker.sock:/var/run/docker.sock

host 的 ``docker_url`` 填 ``unix:///var/run/docker.sock``。

.. warning::

   Docker socket 等价于宿主机 root 权限。生产环境优先使用
   ``agenthub_provisioner_ssh``，或至少给 Docker 端点配置 TLS 与网络隔离。

**TCP + TLS**

remote Docker 守护进程开启 TLS，把 CA/cert/key 挂进 Odoo 容器，host 的
``docker_url`` 填 ``tcp://<host>:2376``，并填写三个 TLS 路径。非 loopback
地址必须启用 TLS。

行为
====

* 只操作带 ``agenthub.managed=true`` label 的容器；同名未托管容器直接报冲突。
* 相同配置 hash 重复 Apply 不重建；配置变化时先停旧容器再建新容器。
* 镜像白名单由 ``agenthub.provisioner.allowed_images`` 控制。

设计文档
========

* ``docs/requirements.md``
* ``docs/design.md``
* ``docs/acceptance.md``
