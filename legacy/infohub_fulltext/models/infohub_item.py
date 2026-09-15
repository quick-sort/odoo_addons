"""条目上的正文提取状态。

为什么这几个字段直接加在 ``infohub.item`` 上，而不是像论文那样放载荷表
（ADR-005）：载荷表是给**介质特有的结构化数据**用的，而正文提取是**横切的处理
状态**，与介质无关（文章、论文、社交内容都可能需要）。为一个处理状态单开一张表
反而会让"哪些条目待处理"的查询变成联表。
"""

from odoo import _, fields, models


class InfohubItem(models.Model):
    _inherit = "infohub.item"

    fulltext_state = fields.Selection(
        [
            ("pending", "待提取"),
            ("done", "已提取"),
            ("skipped", "无需提取"),
            ("failed", "提取失败"),
        ],
        string="正文提取",
        default="pending",
        index=True,
        readonly=True,
        help="记录处理结果，避免对同一条目反复重试。",
    )
    fulltext_error = fields.Text(string="提取错误", readonly=True)
    fulltext_length = fields.Integer(
        string="提取字符数", readonly=True, help="成功提取到的正文字符数。"
    )

    def action_fulltext_retry(self):
        """把条目重置为待提取并立即派发任务。

        给管理员用：来源站改版后，之前失败的条目可以重跑。
        """
        self.write(
            {"fulltext_state": "pending", "fulltext_error": False}
        )
        for source, items in self._group_by_source().items():
            items.with_delay(
                channel=source._queue_channel(),
                description=_("InfoHub 正文提取（手工重试）：%s", source.display_name),
            )._run_enrichment()
        return True
