"""摘要的生成与发送。

挂在 ``res.users`` 上而不是订阅上，因为一封邮件覆盖该用户该周期的**全部**订阅
（否则订了 10 个学科就收 10 封）。
"""

import logging

from odoo import _, api, fields, models
from odoo.fields import Domain

_logger = logging.getLogger(__name__)

#: 一封摘要里最多列多少条。超过就截断并提示"还有 N 条"——邮件不是无限长的载体
MAX_ITEMS_PER_DIGEST = 30

#: 一轮 cron 最多处理多少个用户，避免单次任务跑太久
MAX_USERS_PER_RUN = 200


class ResUsers(models.Model):
    _inherit = "res.users"

    # ==================================================================
    # 内容
    # ==================================================================
    def _infohub_digest_domain(self, frequency, since):
        """该用户该周期的摘要条目 domain。

        只取"命中订阅 ∧ 已发布 ∧ 本周期内发布 ∧ 未读"的条目。未读用 ``not any``
        生成 NOT EXISTS 子查询，不物化已读 ID 列表。

        注意只统计 ``digest_frequency`` 等于该周期的订阅：用户可以把一部分订阅设成
        不推送，那些内容不该出现在邮件里。
        """
        self.ensure_one()
        subscriptions = self.infohub_subscription_ids.filtered(
            lambda s: s.active and s.digest_frequency == frequency
        )
        if not subscriptions:
            return Domain.FALSE

        domain = subscriptions._timeline_domain()
        if domain.is_false():
            return domain

        domain &= Domain("state", "=", "published")
        domain &= Domain("published_at", ">=", since)

        if self.share:
            # portal 用户看不到 internal 源的内容
            domain &= Domain("access_level", "=", "public")
        if self.infohub_muted_tag_ids:
            domain &= Domain("tag_ids", "not in", self.infohub_muted_tag_ids.ids)
        domain &= self._infohub_lang_domain()

        # 未读，且没被用户隐藏
        domain &= Domain(
            "read_ids", "not any", [("user_id", "=", self.id), ("is_read", "=", True)]
        )
        domain &= Domain(
            "read_ids", "not any", [("user_id", "=", self.id), ("is_hidden", "=", True)]
        )
        return domain

    def _infohub_digest_items(self, frequency, since, limit=MAX_ITEMS_PER_DIGEST):
        """取摘要条目。按评分和发布时间排序——评分高的放前面。"""
        self.ensure_one()
        domain = self._infohub_digest_domain(frequency, since)
        if domain.is_false():
            return self.env["infohub.item"], 0
        Item = self.env["infohub.item"]
        total = Item.search_count(domain)
        items = Item.search(
            domain, order="score desc, published_at desc, id desc", limit=limit
        )
        return items, total

    # ==================================================================
    # 发送
    # ==================================================================
    def _infohub_send_digest(self, frequency, now=None):
        """给这些用户发该周期的摘要。逐个记录发送结果。

        单个用户失败不影响其余：邮件服务器拒收一封不该让整轮中断。
        """
        Log = self.env["infohub.digest.log"]
        now = now or fields.Datetime.now()
        since = Log.period_start(frequency, now)
        sent = Log

        for user in self:
            if Log.already_sent(user, frequency, now):
                continue
            try:
                sent |= user._infohub_send_one_digest(frequency, since, now)
            except Exception as exc:  # noqa: BLE001 - 邮件失败形态多，不能中断整轮
                _logger.exception(
                    "InfoHub 摘要：给用户 %s 发送 %s 摘要失败", user.login, frequency
                )
                sent |= Log.create(
                    {
                        "user_id": user.id,
                        "frequency": frequency,
                        "state": "failed",
                        "error": f"{type(exc).__name__}: {exc}",
                    }
                )
        return sent

    def _infohub_send_one_digest(self, frequency, since, now):
        """给单个用户发一封摘要，返回发送记录。"""
        self.ensure_one()
        Log = self.env["infohub.digest.log"]

        if not self.email:
            return Log.create(
                {
                    "user_id": self.id,
                    "frequency": frequency,
                    "state": "failed",
                    "error": _("用户没有邮箱地址。"),
                }
            )

        items, total = self._infohub_digest_items(frequency, since)
        if not items:
            # 记成 skipped 而不是什么都不做：否则每轮 cron 都会为这个用户重算一遍
            return Log.create(
                {
                    "user_id": self.id,
                    "frequency": frequency,
                    "state": "skipped",
                    "item_count": 0,
                }
            )

        body = self._infohub_render_digest(frequency, items, total, since)
        subject = self._infohub_digest_subject(frequency, total)

        mail = self.env["mail.mail"].sudo().create(
            {
                "subject": subject,
                "body_html": body,
                "email_to": self.email,
                "email_from": self.env.company.email or self.env.user.email_formatted,
                "auto_delete": False,
            }
        )
        mail.send(raise_exception=False)

        return Log.create(
            {
                "user_id": self.id,
                "frequency": frequency,
                "state": "sent",
                "item_count": len(items),
                "mail_id": mail.id,
            }
        )

    def _infohub_digest_subject(self, frequency, total):
        self.ensure_one()
        label = _("每日") if frequency == "daily" else _("每周")
        return _("%(period)sInfoHub 摘要：%(count)s 条新内容", period=label, count=total)

    def _infohub_render_digest(self, frequency, items, total, since):
        """渲染邮件正文。

        用 ``ir.qweb`` 渲染一个 ``ir.ui.view``，而不是 ``mail.template``：模板正文
        需要遍历"该用户该周期的未读条目"，mail.template 的渲染上下文只有 ``object``，
        拿这套动态数据很别扭。视图本身仍是数据库记录，管理员照样能改。
        """
        self.ensure_one()
        base_url = (
            self.env["ir.config_parameter"].sudo().get_param("web.base.url") or ""
        ).rstrip("/")
        return self.env["ir.qweb"]._render(
            "infohub_digest.digest_email",
            {
                "user": self,
                "items": items,
                "total": total,
                "shown": len(items),
                "frequency": frequency,
                "since": since,
                "base_url": base_url,
            },
        )

    # ==================================================================
    # cron 入口
    # ==================================================================
    @api.model
    def _cron_infohub_send_digests(self, frequency=None, limit=MAX_USERS_PER_RUN):
        """cron 入口：给所有有该周期订阅的用户发摘要。

        不传 frequency 就两个周期都跑。每日 cron 每天跑一次即可——``already_sent``
        会保证同一周期内不重复发，所以多跑几次也无害。
        """
        frequencies = [frequency] if frequency else ["daily", "weekly"]
        total = self.env["infohub.digest.log"]

        for freq in frequencies:
            subscriptions = self.env["infohub.subscription"].search(
                [("digest_frequency", "=", freq), ("active", "=", True)]
            )
            users = subscriptions.user_id.filtered(lambda u: u.active and u.email)
            if not users:
                continue
            _logger.info(
                "InfoHub 摘要：%s 周期共 %s 个待处理用户", freq, len(users)
            )
            total |= users[:limit]._infohub_send_digest(freq)
        return len(total)

    def action_infohub_send_digest_now(self):
        """手工立即发送（忽略"本周期已发过"的判定），供后台按钮调试用。"""
        Log = self.env["infohub.digest.log"]
        now = fields.Datetime.now()
        for user in self:
            for freq in ("daily", "weekly"):
                has = user.infohub_subscription_ids.filtered(
                    lambda s: s.active and s.digest_frequency == freq
                )
                if has:
                    user._infohub_send_one_digest(
                        freq, Log.period_start(freq, now), now
                    )
        return True
