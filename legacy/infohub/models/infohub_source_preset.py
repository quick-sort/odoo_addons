"""源预设（R1.3、ADR-019）。

三个维度（介质/传输/来源）对管理员是认知负担，而且容易配出无效组合。各渠道
模块以 ``noupdate="1"`` 数据文件提供预设，管理员建源时选一个预设即自动填好
三轴与端点。

这是把模块数量压成次线性（N10）的落点：日常"加一个期刊/板块"退化成加一条
数据记录，而不是写一个模块。
"""

from odoo import _, api, fields, models
from odoo.exceptions import UserError


class InfohubSourcePreset(models.Model):
    _name = "infohub.source.preset"
    _description = "InfoHub 源预设"
    _order = "sequence, name"

    name = fields.Char(string="名称", required=True, translate=True)
    sequence = fields.Integer(string="序号", default=10)
    active = fields.Boolean(string="启用", default=True)
    description = fields.Text(string="说明", translate=True)

    # 三个维度的取值直接从 infohub.source 借来：卫星模块只需在 source 上
    # _selection_add，预设的下拉框会自动出现新选项，不必两处维护。
    medium = fields.Selection(
        selection=lambda self: self._selection_from_source("medium"),
        string="介质",
        required=True,
    )
    transport = fields.Selection(
        selection=lambda self: self._selection_from_source("transport"),
        string="传输",
        required=True,
    )
    provider = fields.Selection(
        selection=lambda self: self._selection_from_source("provider"),
        string="来源",
        required=True,
        default="generic",
    )

    endpoint = fields.Char(string="端点")
    interval_number = fields.Integer(string="间隔", default=1)
    interval_type = fields.Selection(
        [
            ("minutes", "分钟"),
            ("hours", "小时"),
            ("days", "天"),
            ("weeks", "周"),
        ],
        string="间隔单位",
        default="hours",
    )
    min_request_interval = fields.Float(string="最小请求间隔（秒）", default=0.0)
    topic_ids = fields.Many2many(
        "infohub.topic",
        "infohub_preset_topic_rel",
        "preset_id",
        "topic_id",
        string="默认学科",
    )
    default_tag_ids = fields.Many2many(
        "infohub.tag",
        "infohub_preset_tag_rel",
        "preset_id",
        "tag_id",
        string="默认标签",
    )
    requires_credential = fields.Boolean(
        string="需要凭证",
        help="勾选后，用本预设建源时必须指定凭证。",
    )

    @api.model
    def _selection_from_source(self, field_name):
        """把 ``infohub.source`` 上某个 Selection 的取值原样借来用。

        这样卫星模块只需在 ``infohub.source`` 上 ``_selection_add``，预设的
        下拉框会自动跟着出现新选项，不必两处维护。
        """
        return (
            self.env["infohub.source"]
            ._fields[field_name]
            ._description_selection(self.env)
        )

    def _source_vals(self, extra=None):
        """生成 ``infohub.source`` 的 vals。"""
        self.ensure_one()
        vals = {
            "name": self.name,
            "medium": self.medium,
            "transport": self.transport,
            "provider": self.provider,
            "endpoint": self.endpoint,
            "interval_number": self.interval_number or 1,
            "interval_type": self.interval_type or "hours",
            "min_request_interval": self.min_request_interval,
        }
        if self.topic_ids:
            vals["topic_ids"] = [(6, 0, self.topic_ids.ids)]
        if self.default_tag_ids:
            vals["default_tag_ids"] = [(6, 0, self.default_tag_ids.ids)]
        if extra:
            vals.update(extra)
        if self.requires_credential and not vals.get("credential_id"):
            raise UserError(
                _("预设「%s」需要凭证，请先在动作里指定一个凭证。", self.name)
            )
        return vals

    def action_create_source(self):
        """按预设创建源并打开它。"""
        self.ensure_one()
        source = self.env["infohub.source"].create(self._source_vals())
        return {
            "type": "ir.actions.act_window",
            "name": _("信息源"),
            "res_model": "infohub.source",
            "res_id": source.id,
            "view_mode": "form",
            "target": "current",
        }
