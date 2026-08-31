"""学科/领域受控词表。

与 ``infohub.tag`` 的区别：

* topic 是**层级受控**词表，由管理员维护，是订阅的主要维度
* tag 是扁平自由词表，来自规则引擎、LLM 或人工，不保证质量

``_parent_store = True`` 是必需的：订阅按学科走 ``child_of`` 查询（订阅
"计算机科学"要自动覆盖全部子学科），没有 ``parent_path`` 物化路径这个查询
会退化成递归查表。
"""

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class InfohubTopic(models.Model):
    _name = "infohub.topic"
    _description = "InfoHub 学科"
    _parent_store = True
    _parent_name = "parent_id"
    _order = "complete_name"
    _rec_name = "complete_name"

    # 翻译字段只支持 trigram 索引（Odoo 19 会忽略 index=True 并告警）
    name = fields.Char(string="名称", required=True, translate=True, index="trigram")
    code = fields.Char(
        string="编码",
        index=True,
        help="学科的稳定标识，例如 cs 或 cs.LG。用于数据文件引用与外部分类码映射。",
    )
    parent_id = fields.Many2one(
        "infohub.topic",
        string="上级学科",
        ondelete="cascade",
        index=True,
    )
    parent_path = fields.Char(index=True)
    child_ids = fields.One2many("infohub.topic", "parent_id", string="子学科")
    complete_name = fields.Char(
        string="全称",
        compute="_compute_complete_name",
        store=True,
        recursive=True,
    )
    active = fields.Boolean(string="启用", default=True)
    sequence = fields.Integer(string="序号", default=10)
    description = fields.Text(string="说明", translate=True)

    #: 供 portal 注册时建立默认订阅用（R9.6）
    is_recommended = fields.Boolean(
        string="推荐订阅",
        help="勾选后，新注册的读者会自动订阅该学科，避免首屏时间线为空。",
    )

    mapping_ids = fields.One2many(
        "infohub.topic.mapping", "topic_id", string="外部分类码映射"
    )
    item_count = fields.Integer(
        string="条目数",
        compute="_compute_item_count",
        help="直接标注为本学科的条目数，不含子学科。",
    )

    _code_uniq = models.Constraint(
        "UNIQUE(code)",
        "学科编码必须唯一。",
    )

    @api.depends("name", "parent_id.complete_name")
    def _compute_complete_name(self):
        for topic in self:
            if topic.parent_id:
                topic.complete_name = f"{topic.parent_id.complete_name} / {topic.name}"
            else:
                topic.complete_name = topic.name

    def _compute_item_count(self):
        """直接标注的条目数。

        故意不做"含子学科"的汇总：同时标注了父学科与子学科的条目会被重复
        计数，为一个计数字段引入这种歧义不值得。需要含子学科的数量时，请在
        条目列表里按 ``topic_ids child_of`` 过滤后看记录数。

        用一次 ``_read_group`` 算完全部，避免每个学科一次 search_count。
        """
        counts = {}
        if self.ids:
            counts = {
                topic.id: count
                for topic, count in self.env["infohub.item"]._read_group(
                    [("topic_ids", "in", self.ids)],
                    groupby=["topic_ids"],
                    aggregates=["__count"],
                )
            }
        for topic in self:
            topic.item_count = counts.get(topic.id, 0)

    @api.constrains("parent_id")
    def _check_topic_recursion(self):
        if self._has_cycle():
            raise ValidationError(_("学科的层级关系不能形成循环。"))

    def action_view_items(self):
        """打开该学科（含子学科）的条目列表。"""
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("「%s」的条目", self.complete_name),
            "res_model": "infohub.item",
            "view_mode": "list,form",
            "domain": [("topic_ids", "child_of", self.id)],
            "context": {"search_default_group_by_source": 1},
        }
