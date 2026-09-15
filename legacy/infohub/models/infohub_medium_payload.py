"""介质载荷契约。

介质特有的结构化字段放在各自的载荷表里，不加到 ``infohub.item`` 上（ADR-005）。
理由：

* 核心表不随介质数量膨胀（论文、社交、未来的视频/专利/数据集……）
* 卸载介质模块时其表整体消失，不在核心表留下孤儿列
* 每个介质模块完整拥有自己的 schema

代价是显示介质字段需要 join。缓解手段是在 ``infohub.item`` 上为最常用的一两个
字段开 ``related``（例如论文的 DOI）。

介质模块这样用::

    class InfohubPaper(models.Model):
        _name = "infohub.paper"
        _inherit = "infohub.medium.payload"

        doi = fields.Char(index=True)
        ...

并在对应的 medium component 上声明 ``_payload_model = "infohub.paper"``。
"""

from odoo import fields, models


class InfohubMediumPayload(models.AbstractModel):
    _name = "infohub.medium.payload"
    _description = "InfoHub 介质载荷"

    item_id = fields.Many2one(
        "infohub.item",
        string="条目",
        required=True,
        index=True,
        ondelete="cascade",
    )

    #: 一个条目只能有一份载荷。用 Constraint 而非 UniqueIndex，因为这里不需要
    #: 部分索引，且违反时希望给用户看到明确提示。
    _item_uniq = models.Constraint(
        "UNIQUE(item_id)",
        "每个条目只能有一份介质载荷。",
    )
