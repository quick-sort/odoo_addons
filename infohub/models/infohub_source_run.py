"""抓取运行日志（R2.4）。

没有这个模型，线上排查抓取问题基本靠猜：源为什么没出新条目？是没抓到、抓到了
但被去重、还是解析失败？每轮都记下来才能回答。
"""

from odoo import api, fields, models


class InfohubSourceRun(models.Model):
    _name = "infohub.source.run"
    _description = "InfoHub 抓取日志"
    _order = "date_started desc, id desc"
    _rec_name = "source_id"

    source_id = fields.Many2one(
        "infohub.source",
        string="来源",
        required=True,
        index=True,
        ondelete="cascade",
    )
    state = fields.Selection(
        [
            ("running", "进行中"),
            ("done", "成功"),
            ("failed", "失败"),
        ],
        string="状态",
        required=True,
        default="running",
        index=True,
        help=(
            "实践中很少看到「进行中」：日志记录在抓取结束时才写入。"
            "原因是未提交的行对其他事务不可见，「进行中」状态起不到监控作用；"
            "要看正在执行的任务请查 queue_job 的任务列表。"
        ),
    )
    date_started = fields.Datetime(
        string="开始时间", required=True, default=fields.Datetime.now, readonly=True
    )
    date_finished = fields.Datetime(string="结束时间", readonly=True)
    duration = fields.Float(
        string="耗时（秒）", compute="_compute_duration", store=True
    )

    item_found = fields.Integer(string="发现条目", readonly=True)
    item_created = fields.Integer(string="新建条目", readonly=True)
    item_skipped = fields.Integer(
        string="跳过条目",
        readonly=True,
        help="因重复或缺少标题而未入库的条目数。",
    )
    error = fields.Text(string="错误", readonly=True)

    _state_date_idx = models.Index("(source_id, date_started DESC)")

    @api.depends("date_started", "date_finished")
    def _compute_duration(self):
        for run in self:
            if run.date_started and run.date_finished:
                run.duration = (run.date_finished - run.date_started).total_seconds()
            else:
                run.duration = 0.0

    @api.model
    def _gc_runs(self, keep_days=90):
        """清理过期日志，供 cron 调用。"""
        limit = fields.Datetime.subtract(fields.Datetime.now(), days=keep_days)
        old = self.search([("date_started", "<", limit)])
        count = len(old)
        old.unlink()
        return count
