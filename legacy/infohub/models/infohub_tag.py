"""自由标签。

与 ``infohub.topic`` 的分工见该模型的文档字符串：topic 是受控层级词表，
tag 是扁平自由词表，来自规则引擎、LLM 或人工。两者都可被订阅。
"""

from odoo import fields, models


class InfohubTag(models.Model):
    _name = "infohub.tag"
    _description = "InfoHub 标签"
    _order = "name"

    # name 不设 translate：翻译字段在 Odoo 19 存为 jsonb，UNIQUE 约束会退化成
    # 比较整个 JSON 值，无法真正防重。标签多来自源数据与规则引擎，本身不适合翻译。
    name = fields.Char(string="名称", required=True, index=True)
    color = fields.Integer(string="颜色")
    active = fields.Boolean(string="启用", default=True)
    description = fields.Text(string="说明")

    _name_uniq = models.Constraint(
        "UNIQUE(name)",
        "标签名称必须唯一。",
    )
