"""按 feed 的 ``<category>`` 做宽松学科归类。

RSS 的分类是自由文本，没有受控编码，所以这里只能按名称做宽松匹配：先查
``infohub.topic.mapping``（provider = ``rss``，管理员可以手工维护映射），
再退回按学科名称精确匹配。都匹配不上就交给源的默认学科。

这与 arXiv 那类有受控分类码的来源形成对比——后者能做精确映射，属于渠道模块
自己的 classifier。
"""

import logging

from odoo.addons.component.core import Component

_logger = logging.getLogger(__name__)

#: 本 classifier 在 infohub.topic.mapping 里使用的 provider 作用域。
#: 故意不用源的 provider（generic）：generic 会被其他传输共用，
#: 而这里的映射语义是"RSS 分类名 → 学科"。
MAPPING_PROVIDER = "rss"


class RssClassifier(Component):
    _name = "infohub.classifier.rss"
    _inherit = "infohub.classifier.base"
    _usage = "classifier"
    #: 不限 provider，只要传输是 rss 就适用。注意基类是按 provider/medium 匹配的，
    #: 所以这里用 _component_match 换成按 transport 匹配。
    _provider = None
    _medium = None

    @classmethod
    def _component_match(cls, work, usage=None, model_name=None, **kw):
        source = cls._work_source(work)
        return bool(source) and source.transport == "rss"

    def classify(self, item, entry):
        names = self._category_names(entry)
        if not names:
            return False

        topics = self.env["infohub.topic.mapping"].resolve(MAPPING_PROVIDER, names)
        if not topics:
            topics = self.env["infohub.topic"].search([("name", "in", names)])
        if not topics:
            return False

        item.topic_ids = [(4, topic.id) for topic in topics]
        if not item.primary_topic_id:
            item.primary_topic_id = topics[0]
        return True

    @staticmethod
    def _category_names(entry):
        """从 feed 条目里取出分类名，去重且保序。"""
        names = []
        for tag in entry.get("tags") or []:
            term = tag.get("term") if isinstance(tag, dict) else tag
            if term:
                cleaned = " ".join(str(term).split())
                if cleaned and cleaned not in names:
                    names.append(cleaned)
        category = entry.get("category")
        if category:
            cleaned = " ".join(str(category).split())
            if cleaned and cleaned not in names:
                names.append(cleaned)
        return names
