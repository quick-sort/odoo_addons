"""在 transport 维度上加 ``web``，并关联选择器配置。

只扩展一个维度（N9）。介质与来源两轴不碰：网页采集既能产出文章，也能产出论文
（把源的介质设成「论文」，DOI 去重就自动生效——见 infohub_paper 的说明）。
"""

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class InfohubSource(models.Model):
    _inherit = "infohub.source"

    transport = fields.Selection(
        selection_add=[("web", "网页选择器")],
        ondelete={"web": "cascade"},
    )
    web_profile_id = fields.Many2one(
        "infohub.web.profile",
        string="采集配置",
        ondelete="restrict",
        help="传输方式为「网页选择器」时必填。多个源可以共用同一份配置。",
    )

    @api.constrains("transport", "web_profile_id")
    def _check_web_profile(self):
        for source in self:
            if source.transport == "web" and not source.web_profile_id:
                raise ValidationError(
                    _("传输方式为「网页选择器」的源必须指定采集配置。")
                )
