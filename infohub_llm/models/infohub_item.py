"""条目上的 LLM 产出与处理状态。

产出写在**独立字段**，不覆盖 ``summary`` / ``title``（见模块 README 的理由）。
处理状态与 ``infohub_fulltext`` 同一个模式：横切的处理状态放核心条目表，不进介质
载荷表（那是给介质特有的结构化数据用的，ADR-005）。
"""

from odoo import _, fields, models


class InfohubItem(models.Model):
    _inherit = "infohub.item"

    llm_summary = fields.Text(
        string="LLM 摘要", readonly=True, help="由 LLM 生成，不覆盖原摘要。"
    )
    llm_translated_title = fields.Char(string="LLM 译文标题", readonly=True)
    llm_translated_summary = fields.Text(string="LLM 译文摘要", readonly=True)
    llm_state = fields.Selection(
        [
            ("pending", "待处理"),
            ("done", "已处理"),
            ("skipped", "无需处理"),
            ("failed", "处理失败"),
        ],
        string="LLM 处理",
        default="pending",
        index=True,
        readonly=True,
        help="记录处理结果，避免对同一条目反复调用（每次调用都要花钱）。",
    )
    llm_error = fields.Text(string="LLM 错误", readonly=True)

    def action_llm_retry(self):
        """重置为待处理并立即派发任务。"""
        self.write({"llm_state": "pending", "llm_error": False})
        for source, items in self._group_by_source().items():
            items.with_delay(
                channel=source._queue_channel(),
                description=_("InfoHub LLM 增强（手工重试）：%s", source.display_name),
            )._run_enrichment()
        return True
