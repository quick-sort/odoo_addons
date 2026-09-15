"""摘要发送记录。

存在的理由是**幂等**：到期判定为"该 (用户, 周期) 在本周期内还没有成功发送记录"，
而不是在用户或订阅上放一个 ``last_digest_at`` 时间戳。差别在于 cron 重跑、多 worker
并发、发送中途失败这几种情况下，日志能给出准确答案，而单个时间戳会漏发或重发。

顺带也是运营需要的东西：谁在什么时候收到了几条内容、有没有发失败。
"""

from odoo import _, api, fields, models

#: 各周期对应的回溯天数
PERIOD_DAYS = {"daily": 1, "weekly": 7}


class InfohubDigestLog(models.Model):
    _name = "infohub.digest.log"
    _description = "InfoHub 摘要发送记录"
    _order = "date_sent desc, id desc"
    _rec_name = "user_id"

    user_id = fields.Many2one(
        "res.users", string="收件人", required=True, index=True, ondelete="cascade"
    )
    frequency = fields.Selection(
        [("daily", "每日"), ("weekly", "每周")],
        string="周期",
        required=True,
        index=True,
    )
    date_sent = fields.Datetime(
        string="发送时间", required=True, default=fields.Datetime.now, readonly=True
    )
    item_count = fields.Integer(string="条目数", readonly=True)
    state = fields.Selection(
        [("sent", "已发送"), ("skipped", "无内容跳过"), ("failed", "发送失败")],
        string="状态",
        required=True,
        default="sent",
        index=True,
    )
    error = fields.Text(string="错误", readonly=True)
    mail_id = fields.Many2one("mail.mail", string="邮件", ondelete="set null")

    _user_period_idx = models.Index("(user_id, frequency, date_sent DESC)")

    # ==================================================================
    @api.model
    def period_start(self, frequency, now=None):
        """本周期的起点。"""
        now = now or fields.Datetime.now()
        return fields.Datetime.subtract(now, days=PERIOD_DAYS.get(frequency, 1))

    @api.model
    def already_sent(self, user, frequency, now=None):
        """该 (用户, 周期) 在本周期内是否已经发过。

        ``skipped``（无内容）也算已处理：否则每次 cron 都会为没有新内容的用户重复
        计算一遍条目。``failed`` 不算，留给下一轮重试。
        """
        return bool(
            self.search_count(
                [
                    ("user_id", "=", user.id),
                    ("frequency", "=", frequency),
                    ("state", "in", ("sent", "skipped")),
                    ("date_sent", ">=", self.period_start(frequency, now)),
                ]
            )
        )

    @api.model
    def _gc_logs(self, keep_days=180):
        """清理过期记录，供 cron 调用。"""
        limit = fields.Datetime.subtract(fields.Datetime.now(), days=keep_days)
        old = self.search([("date_sent", "<", limit)])
        count = len(old)
        old.unlink()
        return count

    def action_view_items(self):
        """打开这封摘要覆盖的时间段内该用户的条目。"""
        self.ensure_one()
        since = self.env["infohub.digest.log"].period_start(
            self.frequency, self.date_sent
        )
        domain = self.user_id._infohub_timeline_domain()
        return {
            "type": "ir.actions.act_window",
            "name": _("「%s」的摘要内容", self.user_id.name),
            "res_model": "infohub.item",
            "view_mode": "list,form",
            "domain": list(domain) + [("published_at", ">=", since)],
        }
