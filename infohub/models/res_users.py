"""用户上的 InfoHub 阅读偏好。

订阅是每用户的，屏蔽标签与语言偏好则是全局作用于该用户的整条时间线（R7.3）。

portal 读者要能在 website 端读写自己的这些偏好，所以必须把字段加进
``SELF_READABLE_FIELDS`` / ``SELF_WRITEABLE_FIELDS``——否则 portal 用户读自己的
用户记录时会被拒。这两个属性在 Odoo 19 是 ``@property``，用属性覆盖来扩展。
"""

from odoo import api, fields, models
from odoo.fields import Domain

#: portal 读者可读写的 InfoHub 偏好字段
INFOHUB_SELF_FIELDS = [
    "infohub_muted_tag_ids",
    "infohub_lang_filter",
]


class ResUsers(models.Model):
    _inherit = "res.users"

    infohub_subscription_ids = fields.One2many(
        "infohub.subscription",
        "user_id",
        string="InfoHub 订阅",
    )
    infohub_subscription_count = fields.Integer(
        string="订阅数", compute="_compute_infohub_subscription_count"
    )
    infohub_muted_tag_ids = fields.Many2many(
        "infohub.tag",
        "infohub_user_muted_tag_rel",
        "user_id",
        "tag_id",
        string="屏蔽标签",
        help="带这些标签的条目不会出现在你的时间线里。",
    )
    infohub_lang_filter = fields.Char(
        string="关注语言",
        help=(
            "留空表示不限语言。填写语言代码前缀，多个用英文逗号分隔，例如 "
            "zh,en。按前缀匹配，所以 zh 同时命中 zh-CN 与 zh-TW。"
        ),
    )

    @property
    def SELF_READABLE_FIELDS(self):
        return super().SELF_READABLE_FIELDS + INFOHUB_SELF_FIELDS

    @property
    def SELF_WRITEABLE_FIELDS(self):
        return super().SELF_WRITEABLE_FIELDS + INFOHUB_SELF_FIELDS

    @api.depends("infohub_subscription_ids")
    def _compute_infohub_subscription_count(self):
        for user in self:
            user.infohub_subscription_count = len(
                user.infohub_subscription_ids.filtered("active")
            )

    # ==================================================================
    # 时间线
    # ==================================================================
    def _infohub_lang_domain(self):
        """语言过滤 domain。

        按前缀匹配：偏好里写 ``zh`` 能命中 ``zh-CN`` 与 ``zh-TW``。语言未知
        （``lang`` 为空）的条目一律保留——宁可多给，不要因为源没声明语言就
        让用户看不到内容。
        """
        self.ensure_one()
        if not self.infohub_lang_filter:
            return Domain.TRUE
        prefixes = [
            code.strip()
            for code in self.infohub_lang_filter.split(",")
            if code.strip()
        ]
        if not prefixes:
            return Domain.TRUE
        domain = Domain("lang", "=", False)
        for prefix in prefixes:
            domain |= Domain("lang", "=ilike", f"{prefix}%")
        return domain

    def _infohub_timeline_domain(self, include_hidden=False):
        """当前用户的时间线 domain（ADR-003 拉取式）。

        = 订阅并集
          ∧ 已发布
          ∧ 来源可见范围允许
          ∧ 非屏蔽标签
          ∧ 语言偏好
          ∧ 未被用户隐藏

        :param bool include_hidden: 是否包含用户主动隐藏的条目
        """
        self.ensure_one()
        domain = self.infohub_subscription_ids._timeline_domain()
        if domain.is_false():
            return domain

        domain &= Domain("state", "=", "published")

        # 内部源只对内部用户可见（ADR-015）
        if self.share:
            domain &= Domain("access_level", "=", "public")

        if self.infohub_muted_tag_ids:
            domain &= Domain(
                "tag_ids", "not in", self.infohub_muted_tag_ids.ids
            )

        domain &= self._infohub_lang_domain()

        if not include_hidden:
            # 同样用 not any 走 NOT EXISTS 子查询，不物化 ID 列表
            domain &= Domain(
                "read_ids",
                "not any",
                [("user_id", "=", self.id), ("is_hidden", "=", True)],
            )

        return domain

    def _infohub_timeline_items(self, limit=None, offset=0, extra_domain=None):
        """按时间线 domain 取条目。"""
        self.ensure_one()
        domain = self._infohub_timeline_domain()
        if extra_domain:
            domain &= Domain(extra_domain)
        return self.env["infohub.item"].search(
            domain, limit=limit, offset=offset, order="published_at desc, id desc"
        )

    # ==================================================================
    # 默认订阅（R9.6）
    # ==================================================================
    def _infohub_ensure_default_subscriptions(self):
        """为用户建立默认订阅，避免首屏时间线为空。

        取标记为「推荐订阅」的学科与信息源。已有任何订阅的用户不再处理，
        避免覆盖用户自己的选择。``infohub_website`` 在注册后调用本方法。
        """
        Subscription = self.env["infohub.subscription"].sudo()
        topics = self.env["infohub.topic"].sudo().search([("is_recommended", "=", True)])
        sources = self.env["infohub.source"].sudo().search([("is_recommended", "=", True)])
        if not topics and not sources:
            return Subscription

        created = Subscription
        for user in self:
            if Subscription.search_count([("user_id", "=", user.id)]):
                continue
            vals_list = [
                {"user_id": user.id, "target_type": "topic", "topic_id": topic.id}
                for topic in topics
            ] + [
                {"user_id": user.id, "target_type": "source", "source_id": source.id}
                for source in sources
            ]
            if vals_list:
                created |= Subscription.create(vals_list)
        return created
