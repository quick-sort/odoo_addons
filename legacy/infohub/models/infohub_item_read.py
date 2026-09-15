"""每用户的条目交互状态。

内容是多人共享的，但已读/收藏/隐藏是每个人自己的，所以这些状态不能放在
``infohub.item`` 上（ADR-004）。

本表必须保持**稀疏**：只为真正发生过交互的 (user, item) 建行（R8.2）。绝不
为「全部用户 × 全部命中条目」预生成——那是 ADR-003 明确否决的扇出式，在
200 用户 × 50 万条目下是 10⁸ 行。

因此"未读数"不能直接 count，要配合 ``infohub.subscription.last_read_at``
水位线来算，见该模型的 ``_unread_domain``。
"""

from odoo import api, fields, models


class InfohubItemRead(models.Model):
    _name = "infohub.item.read"
    _description = "InfoHub 阅读状态"
    _order = "read_at desc, id desc"
    _rec_name = "item_id"

    user_id = fields.Many2one(
        "res.users",
        string="用户",
        required=True,
        index=True,
        ondelete="cascade",
        default=lambda self: self.env.user,
    )
    item_id = fields.Many2one(
        "infohub.item",
        string="条目",
        required=True,
        index=True,
        ondelete="cascade",
    )
    is_read = fields.Boolean(string="已读", default=True)
    read_at = fields.Datetime(string="阅读时间")
    is_starred = fields.Boolean(string="收藏")
    is_hidden = fields.Boolean(
        string="隐藏", help="用户主动从自己的时间线里移除该条目。"
    )

    #: 便于按学科/来源筛选自己的收藏，不必每次联表到 item
    source_id = fields.Many2one(
        related="item_id.source_id", store=True, index=True, readonly=True
    )

    _user_item_uniq = models.Constraint(
        "UNIQUE(user_id, item_id)",
        "同一用户对同一条目只能有一条阅读状态。",
    )
    #: 收藏列表查询。部分索引：只有收藏的行进索引
    _starred_idx = models.Index("(user_id) WHERE is_starred IS TRUE")
    #: 未读判定要按用户排除已读集合
    _user_read_idx = models.Index("(user_id, is_read)")

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if vals.get("is_read", True) and not vals.get("read_at"):
                vals["read_at"] = fields.Datetime.now()
        return super().create(vals_list)
