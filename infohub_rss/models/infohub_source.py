"""在 transport 维度上加一个 ``rss`` 取值。

只扩展一个维度——这是判断模块切分是否正确的检验标准（N9）。介质字段来自
``infohub``（article），来源用核心的 ``generic``，两者都不需要改。
"""

from odoo import fields, models


class InfohubSource(models.Model):
    _inherit = "infohub.source"

    transport = fields.Selection(
        selection_add=[("rss", "RSS / Atom")],
        ondelete={"rss": "cascade"},
    )
