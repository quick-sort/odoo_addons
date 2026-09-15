"""源上的 LLM 开关。

三个开关默认**全关**：LLM 调用要花钱，装上模块不等于同意为每条内容付费。
"""

from odoo import fields, models


class InfohubSource(models.Model):
    _inherit = "infohub.source"

    llm_model_id = fields.Many2one(
        "llm.model",
        string="LLM 模型",
        domain="[('model_use', 'in', ['chat', 'multimodal']), ('active', '=', True)]",
        help="留空则用全局默认的对话模型。",
    )
    llm_summarize = fields.Boolean(
        string="生成摘要",
        help="把长正文压成几句话。结果写在条目的「LLM 摘要」里，不覆盖原摘要。",
    )
    llm_translate_to = fields.Char(
        string="翻译成",
        help=(
            "目标语言，例如 zh 或中文。留空表示不翻译。"
            "只翻译标题与摘要——翻译全文成本高得多，收益却有限。"
        ),
    )
    llm_classify = fields.Boolean(
        string="零样本学科归类",
        help=(
            "让模型从学科词表里挑一个。只在来源**没有**受控分类码时才值得开："
            "arXiv 这类有精确编码的来源用映射表 classifier 又准又免费。"
        ),
    )

    def _llm_enabled(self):
        """本源是否需要 LLM 增强。"""
        self.ensure_one()
        return bool(self.llm_summarize or self.llm_translate_to)
