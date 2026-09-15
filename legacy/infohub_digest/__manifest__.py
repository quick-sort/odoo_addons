{
    "name": "InfoHub 摘要推送",
    "summary": "按订阅周期把未读条目汇总成邮件推送给读者",
    "description": """
InfoHub 摘要推送
================
按读者在订阅上设置的周期（每日 / 每周）把未读条目汇总成一封邮件发出去。

一封邮件，不是一个订阅一封
--------------------------
按 **(用户, 周期)** 分组发送：一个用户订阅了 10 个学科，收到的是**一封**汇总邮件，
而不是 10 封。用户同时有每日和每周订阅时，各收一封。

不做站内通知（ADR-013），对外触达只有这一条渠道。

发送记录用于幂等
----------------
``infohub.digest.log`` 记录每次发送。到期判定是"该 (用户, 周期) 在本周期内还没有
成功发送记录"，而不是靠某个字段上的时间戳——cron 重跑、多 worker 并发时不会重复发。

正文是可编辑的 QWeb 视图
------------------------
没有用 ``mail.template``：模板正文需要遍历"该用户该周期的未读条目"，而 mail.template
的渲染上下文只有 ``object``，拿这套动态数据很别扭。改成渲染一个
``ir.ui.view``（``infohub_digest.digest_email``）再建 ``mail.mail``。视图本身仍然是
数据库记录，管理员照样能改，可编辑性没有损失。
    """,
    "author": "quick-sort@outlook.com",
    "website": "quick-sort@outlook.com",
    "category": "Productivity",
    "version": "19.0.1.0.0",
    "depends": ["infohub"],
    "data": [
        "security/ir.model.access.csv",
        "views/infohub_digest_templates.xml",
        "views/infohub_digest_log_views.xml",
        "views/infohub_menus.xml",
        "data/ir_cron_data.xml",
    ],
    "license": "LGPL-3",
    "installable": True,
    "application": False,
    "auto_install": False,
}
