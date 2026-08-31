"""订阅匹配器 —— 把一条订阅翻译成 ``infohub.item`` 上的 domain。

时间线是拉取式的（ADR-003）：条目只存一份，用户的时间线由其全部订阅的 domain
取并集动态算出。这样改订阅零成本、立即生效，也不需要为「用户 × 条目」预生成行。

新增订阅维度（按作者订阅、按期刊订阅、按关键词订阅……）只需要：

1. 在 ``infohub.subscription.target_type`` 上 ``_selection_add`` 加一个值
2. 加一个 matcher component 声明对应的 ``_target_type``

核心不需要任何改动。

注意 collection 是 ``infohub.subscription`` 而不是 ``infohub.source``——匹配
维度是订阅目标类型，与信息源无关。
"""

from odoo.addons.component.core import AbstractComponent, Component
from odoo.fields import Domain


class SubscriptionMatcherBase(AbstractComponent):
    """订阅匹配器基类。"""

    _name = "infohub.subscription.matcher.base"
    _collection = "infohub.subscription"
    _usage = "subscription.matcher"
    _target_type = None

    @classmethod
    def _component_match(cls, work, usage=None, model_name=None, **kw):
        subscription = getattr(work, "subscription", None)
        return bool(subscription) and cls._target_type == subscription.target_type

    def domain(self, subscription):
        """返回该订阅命中的条目 domain。

        :rtype: odoo.fields.Domain
        """
        raise NotImplementedError


class SourceMatcher(Component):
    """按信息源订阅。"""

    _name = "infohub.subscription.matcher.source"
    _inherit = "infohub.subscription.matcher.base"
    _target_type = "source"

    def domain(self, subscription):
        if not subscription.source_id:
            return Domain.FALSE
        return Domain("source_id", "=", subscription.source_id.id)


class TopicMatcher(Component):
    """按学科订阅。

    用 ``child_of`` 使"订阅计算机科学"自动覆盖其全部子学科，这也是
    ``infohub.topic`` 必须设 ``_parent_store`` 的原因。
    """

    _name = "infohub.subscription.matcher.topic"
    _inherit = "infohub.subscription.matcher.base"
    _target_type = "topic"

    def domain(self, subscription):
        if not subscription.topic_id:
            return Domain.FALSE
        return Domain("topic_ids", "child_of", subscription.topic_id.id)


class TagMatcher(Component):
    """按标签订阅。"""

    _name = "infohub.subscription.matcher.tag"
    _inherit = "infohub.subscription.matcher.base"
    _target_type = "tag"

    def domain(self, subscription):
        if not subscription.tag_id:
            return Domain.FALSE
        return Domain("tag_ids", "in", subscription.tag_id.ids)
