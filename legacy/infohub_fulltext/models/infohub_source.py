"""源上的正文提取开关。

只在 transport/medium/provider 三轴之外加配置字段，不碰任何维度——本模块是
**横切关注点**（enricher），不属于三轴中的任何一轴。
"""

from odoo import fields, models


class InfohubSource(models.Model):
    _inherit = "infohub.source"

    fulltext_enabled = fields.Boolean(
        string="提取正文",
        default=True,
        help=(
            "对本源的条目按需抓取原文并提取正文。装了本模块通常就是想用它，"
            "所以默认开启；对不希望额外出网的源可以单独关掉。"
        ),
    )
    fulltext_min_length = fields.Integer(
        string="正文长度阈值",
        default=500,
        help=(
            "现有正文短于该字符数时才去抓原文。设得太小会对本来就有全文的源做无用"
            "请求；设为 0 表示无论多长都抓（不建议）。"
        ),
    )
