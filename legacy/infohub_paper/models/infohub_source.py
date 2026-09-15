"""在 medium 维度上加一个 ``paper`` 取值。

**只扩展一个维度**——这是判断模块切分是否正确的检验标准（N9）。传输与来源两轴
完全不碰：论文可以经 RSS、HTTP API、网页爬取任意一种传输进来。
"""

from odoo import fields, models


class InfohubSource(models.Model):
    _inherit = "infohub.source"

    medium = fields.Selection(
        selection_add=[("paper", "论文")],
        ondelete={"paper": "cascade"},
    )
