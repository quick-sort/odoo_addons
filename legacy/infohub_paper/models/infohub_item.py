"""条目上的论文载荷入口。

只加一个 One2many 用于在表单里内联展示载荷，不加 ``related`` 字段。

关于 design.md 提到的"用 related 把 DOI 提到 item 上"这条缓解手段
----------------------------------------------------------------
实际做不到：``related`` 需要单记录路径，而载荷是 One2many（一对一由唯一约束保证，
类型上仍是 o2m），``related="paper_ids.doi"`` 不成立。要做成 related 就得在 item 上
再放一个 Many2one 反向指回载荷，那等于把一对一关系存两份，反而更容易不一致。

改用的方案是给 ``infohub.paper`` 自己一套列表/搜索视图和菜单：论文场景本来就更常按
论文维度浏览（按作者、按期刊、按 DOI 找），而载荷表上已经把 title / published_at /
source_id / state 做成 store=True 的 related，列表页不需要联表。

这是对 design.md 的一处有意偏离，已在本模块 README 记录。
"""

from odoo import fields, models


class InfohubItem(models.Model):
    _inherit = "infohub.item"

    paper_ids = fields.One2many(
        "infohub.paper",
        "item_id",
        string="论文数据",
        help="介质载荷。一个条目最多一条，唯一性由载荷表的约束保证。",
    )
