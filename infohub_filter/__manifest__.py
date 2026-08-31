{
    "name": "InfoHub 规则引擎",
    "summary": "按规则自动打标签、评分、拒绝条目",
    "description": """
InfoHub 规则引擎
================
在条目审核前插入一组有序规则：自动打标签、加减评分、指派学科、直接拒绝。用来对付
信息过载——把噪声压掉，把真正关心的内容顶上来。

与核心审核的分工（ADR-009）
---------------------------
审核状态机与人工标黑在「核心」，因为 portal 的记录规则依赖 ``item.state``，核心不能
依赖一个可选模块才能保证访问控制正确。本模块只提供规则求值，通过覆盖
``infohub.item._moderate()`` 介入：

* 命中 ``publish`` / ``reject`` 动作的条目由规则直接定状态
* 其余条目交回核心走默认审核（默认发布）

**注意**：卸载本模块后核心必须仍能正常发布。这一条是硬约束，有专门的验收项。

规则求值顺序
------------
按 ``sequence`` 升序。条件由两部分组成，都满足才算命中：

* ``condition_domain`` —— 对 ``infohub.item`` 的 Odoo domain（可留空表示不限）
* ``keyword_regex`` —— 正则，匹配标题 / 正文纯文本 / 两者（可留空表示不限）

动作分两类：

* 终结型（``publish`` / ``reject``）—— 定下状态，该条目不再过后续规则
* 标注型（``tag`` / ``score`` / ``topic``）—— 打完标注继续过后续规则，
  除非勾了 ``stop_after``
    """,
    "author": "quick-sort@outlook.com",
    "website": "quick-sort@outlook.com",
    "category": "Productivity",
    "version": "19.0.1.0.0",
    "depends": ["infohub"],
    "data": [
        "security/ir.model.access.csv",
        "views/infohub_rule_views.xml",
    ],
    "license": "LGPL-3",
    "installable": True,
    "application": False,
    "auto_install": False,
}
