=================
InfoHub 前端阅读
=================

给 portal 读者提供网站端的阅读界面。后台的 Odoo 标准视图保留给内部用户做源管理
与审核。

路由
====

=====================================  ========  ==========================================
路由                                   auth      说明
=====================================  ========  ==========================================
``/infohub``                           user      个人信息流，支持筛选、搜索、分页
``/infohub/page/<n>``                  user      同上，分页
``/infohub/item/<id>``                 user      条目详情，打开即记为已读
``/infohub/subscriptions``             user      订阅与偏好管理（GET/POST）
``/infohub/topic/<id>``                public    公开学科浏览页
``/infohub/item/toggle_star``          user      jsonrpc：收藏切换
``/infohub/item/toggle_hidden``        user      jsonrpc：隐藏切换
``/infohub/item/mark_read``            user      jsonrpc：已读/未读切换
=====================================  ========  ==========================================

另外在 ``/my`` 首页加了一张「我的信息流」卡片，未读数由 portal 的 JS 交互异步拉
``/my/counters`` 填充。

个性化与安全边界的分工
======================

**条目的记录规则只按 ``state`` 与 ``access_level`` 两个索引字段过滤，不按订阅过滤**
（ADR-015）。按 m2m 订阅做记录规则需要联表，在几十万行上会退化成慢查询。订阅是
**展示逻辑**，由 ``res.users._infohub_timeline_domain()`` 在控制器里完成。

这个取舍的前提是"内容都是公开网页信息"，读到未订阅的条目不构成机密泄露。真正
需要隔离的是订阅与阅读状态，它们有 ``user_id = user.id`` 记录规则，并且控制器里
还会再显式过滤一次（防御性）。

**若将来接入付费或内部机密源，这个取舍必须重新评估。**

几个实现上的坑（都已踩过并修正）
================================

公开页不要用 ``<model(...)>`` 转换器
------------------------------------
该转换器会以**当前用户身份** browse 记录。匿名访客是 ``base.public_user``，而我们
没有给 ``base.group_public`` 任何 ACL，转换器会直接失败成 404。公开页用
``<int:id>`` + ``sudo()`` + 显式可见性过滤，好处是不必为一个可选页面放宽整个模型
的 ACL。

用了 ``sudo()`` 就必须自己把可见性条件写全：``state = 'published'`` **且**来源
``access_level = 'public'``。少写一个就等于把内部内容公开出去。

判断"是不是自己的记录"要用 ``search`` 而不是 ``browse().exists()``
------------------------------------------------------------------
``exists()`` 不套记录规则，随后读字段会先抛出 Odoo 原生的 AccessError，用户看到
一段通用权限报错。``search([('id','=',x),('user_id','=',uid)])`` 同时套上记录规则和
显式过滤，别人的记录直接查不到，就能给出明确提示。

Odoo 19 用 ``type='jsonrpc'``
-----------------------------
``type='json'`` 只是废弃别名（``odoo/http.py:762``）。jsonrpc 默认免 CSRF 校验、走
会话认证；普通表单 POST 则**必须**保留 CSRF，模板里带
``<input type="hidden" name="csrf_token" t-att-value="request.csrf_token()"/>``。

模板一律 ``t-out``，禁止 ``t-raw``
---------------------------------
条目正文是第三方 HTML，字段侧已 ``sanitize=True``，输出侧仍必须用 ``t-out``。

自助注册
========

依赖 ``auth_signup``。``res.users._signup_create_user`` 被覆盖，新注册用户会：

1. 加入 ``infohub.group_reader``（否则连条目都读不到）
2. 按标记为「推荐订阅」的学科与信息源建立默认订阅（否则首屏是空的）

**没有**把 ``group_reader`` 挂到 ``base.group_portal`` 的 ``implied_ids`` 上：那会让
库里所有 portal 用户（包括其他应用带来的）都变成 InfoHub 读者，作用面太宽。代价
是既有 portal 用户需要管理员手工加组。

抗注册滥用
----------
本模块只提供**基本**防护：按 IP 的滑动窗口限流（``infohub.signup.attempt``，
自清理、不需要 cron）。可调系统参数::

    infohub.signup_max_attempts    默认 5
    infohub.signup_window_minutes  默认 60

真正的抗滥用要叠加：

* ``auth_signup_uninvited = 'b2b'`` —— 改为仅邀请注册，Odoo 自带的最强开关
* 反向代理层限流（本项目部署里已有 nginx）
* reCAPTCHA —— ``/web/signup`` 在 Odoo 19 已内置 ``captcha='signup'`` 挂载点
  （``auth_signup/controllers/main.py:39``），装上并配置 captcha 实现模块即可生效

**关于邮箱验证的现状**：Odoo 的自助注册不是"先验证邮箱再激活"，它会立即创建账号，
然后发一封账号创建确认邮件。把邮箱验证做成准入门槛需要额外开发，当前不在范围内。

已知限制
========

* 公开学科页 ``sitemap=False``：为任意 id 生成 sitemap 需要一个 callable 生成器，
  当前不做。页面仍可正常分享与访问，只是不会被自动收录。
* 未读计数是非存储计算字段，同一事务内新入库的条目不会立刻反映到计数上。对展示
  用计数器可以接受（每次请求都是新事务）。

测试
====

见 ``.kiro/specs/infohub/http_test.py``（54 项 HTTP 端到端）。需要先在容器里另起一个
只服务测试库的临时 HTTP 服务，命令写在该脚本的文档字符串里。
