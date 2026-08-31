"""每用户订阅。

时间线是拉取式的（ADR-003）：条目只存一份，用户时间线由其全部订阅的 domain
取并集动态算出。改订阅立即生效、零回溯成本。

订阅维度可扩展（R7.2）：新增"按作者订阅""按期刊订阅""按关键词订阅"只需

1. 在 ``target_type`` 上 ``_selection_add`` 加值
2. 加一个 ``infohub.subscription.matcher`` component

核心不需要改动。为此本模型也继承 ``collection.base``，让 matcher 能以
component 形式挂载。
"""

from contextlib import contextmanager

from odoo import _, api, fields, models
from odoo.addons.component.exception import NoComponentError
from odoo.exceptions import ValidationError
from odoo.fields import Domain


class InfohubSubscription(models.Model):
    _name = "infohub.subscription"
    _description = "InfoHub 订阅"
    _inherit = "collection.base"
    _order = "sequence, id"
    _rec_name = "display_name"

    user_id = fields.Many2one(
        "res.users",
        string="用户",
        required=True,
        index=True,
        ondelete="cascade",
        default=lambda self: self.env.user,
    )
    active = fields.Boolean(string="启用", default=True)
    sequence = fields.Integer(string="序号", default=10)

    target_type = fields.Selection(
        [
            ("source", "信息源"),
            ("topic", "学科"),
            ("tag", "标签"),
        ],
        string="订阅类型",
        required=True,
        default="topic",
    )
    source_id = fields.Many2one("infohub.source", string="信息源", ondelete="cascade")
    topic_id = fields.Many2one("infohub.topic", string="学科", ondelete="cascade")
    tag_id = fields.Many2one("infohub.tag", string="标签", ondelete="cascade")

    medium_filter = fields.Char(
        string="介质过滤",
        help="留空表示不限。填写介质代码（多个用英文逗号分隔），例如 paper 或 article,paper。",
    )

    #: 未读水位线。未读 = 命中 domain 且 published_at > last_read_at 且不在已读表中
    last_read_at = fields.Datetime(
        string="已读水位线",
        help="标记「全部已读」时推进到当前时间，使未读计数不必扫描全部历史条目。",
    )
    digest_frequency = fields.Selection(
        [("none", "不推送"), ("daily", "每日"), ("weekly", "每周")],
        string="摘要推送",
        required=True,
        default="none",
    )

    unread_count = fields.Integer(string="未读数", compute="_compute_unread_count")

    _target_consistency = models.Constraint(
        """CHECK(
            (target_type = 'source' AND source_id IS NOT NULL)
            OR (target_type = 'topic' AND topic_id IS NOT NULL)
            OR (target_type = 'tag' AND tag_id IS NOT NULL)
            OR target_type NOT IN ('source', 'topic', 'tag')
        )""",
        "订阅必须指定与订阅类型匹配的目标。",
    )
    #: 同一用户不要对同一目标重复订阅
    _source_uniq = models.UniqueIndex(
        "(user_id, source_id) WHERE source_id IS NOT NULL",
        "已经订阅过该信息源。",
    )
    _topic_uniq = models.UniqueIndex(
        "(user_id, topic_id) WHERE topic_id IS NOT NULL",
        "已经订阅过该学科。",
    )
    _tag_uniq = models.UniqueIndex(
        "(user_id, tag_id) WHERE tag_id IS NOT NULL",
        "已经订阅过该标签。",
    )

    # ==================================================================
    # 展示
    # ==================================================================
    @api.depends("target_type", "source_id", "topic_id", "tag_id")
    def _compute_display_name(self):
        labels = dict(self._fields["target_type"]._description_selection(self.env))
        for subscription in self:
            target = (
                subscription.source_id.display_name
                or subscription.topic_id.display_name
                or subscription.tag_id.display_name
                or _("未指定")
            )
            prefix = labels.get(subscription.target_type, subscription.target_type)
            subscription.display_name = f"{prefix}：{target}"

    # ==================================================================
    # Component 入口
    # ==================================================================
    @contextmanager
    def work_on(self, model_name=None, **kwargs):
        """把订阅记录注入 WorkContext，matcher 的 ``_component_match`` 依赖它。"""
        self.ensure_one()
        kwargs.setdefault("subscription", self)
        with super().work_on(model_name or "infohub.item", **kwargs) as work:
            yield work

    def _matcher(self):
        self.ensure_one()
        try:
            with self.work_on() as work:
                return work.component(usage="subscription.matcher")
        except NoComponentError as exc:
            raise ValidationError(
                _(
                    "订阅类型 %s 没有对应的匹配器实现，请确认已安装提供它的模块。",
                    self.target_type,
                )
            ) from exc

    @api.constrains("target_type")
    def _check_matcher_exists(self):
        for subscription in self:
            subscription._matcher()

    # ==================================================================
    # Domain 构建
    # ==================================================================
    def _domain(self):
        """本条订阅命中的条目 domain。"""
        self.ensure_one()
        domain = Domain(self._matcher().domain(self))
        if self.medium_filter:
            media = [
                code.strip() for code in self.medium_filter.split(",") if code.strip()
            ]
            if media:
                domain &= Domain("medium", "in", media)
        return domain

    def _timeline_domain(self):
        """本记录集（通常是某用户的全部订阅）的时间线 domain。

        只做订阅并集，不含"已发布""屏蔽标签"等全局条件——那些由
        ``res.users._infohub_timeline_domain()`` 统一附加，避免两处重复。
        """
        active = self.filtered("active")
        if not active:
            return Domain.FALSE
        return Domain.OR([subscription._domain() for subscription in active])

    def _unread_domain(self):
        """未读条目 domain。

        水位线把扫描范围限制在"水位线之后发布的条目"，再排除已读集合，
        这样交互表可以一直保持稀疏（R8.3）。

        排除已读用 ``not any`` 生成 NOT EXISTS 子查询，而不是先把已读 ID 全查
        出来再 ``id not in [...]``——重度读者的已读集合可以有几万条，物化成
        Python 列表既慢又会撑大 SQL（N1）。
        """
        self.ensure_one()
        domain = self._domain() & Domain("state", "=", "published")
        if self.last_read_at:
            domain &= Domain("published_at", ">", self.last_read_at)
        domain &= Domain(
            "read_ids",
            "not any",
            [("user_id", "=", self.user_id.id), ("is_read", "=", True)],
        )
        return domain

    @api.depends(
        "last_read_at",
        "active",
        "target_type",
        "source_id",
        "topic_id",
        "tag_id",
        "medium_filter",
    )
    def _compute_unread_count(self):
        """未读数。

        依赖只声明订阅自身的字段：条目侧的变化无法在这里表达（那需要依赖整张
        条目表）。这意味着同一事务内新入库的条目不会立刻反映到计数上——对一个
        展示用计数器可以接受，因为前端每次请求都是新事务。

        没有 ``@api.depends`` 会更糟：改了水位线之后读到的仍是缓存的旧值。
        """
        for subscription in self:
            subscription.unread_count = self.env["infohub.item"].search_count(
                subscription._unread_domain()
            )

    # ==================================================================
    # 动作
    # ==================================================================
    def action_mark_all_read(self):
        """推进水位线，把本订阅下的历史条目视为已读。"""
        self.write({"last_read_at": fields.Datetime.now()})
        return True

    def action_view_items(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": self.display_name,
            "res_model": "infohub.item",
            "view_mode": "list,form",
            "domain": list(self._domain() & Domain("state", "=", "published")),
        }
