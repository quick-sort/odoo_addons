"""arXiv 分类码到学科的归类。

与 RSS 的宽松名称匹配形成对比：arXiv 有**受控分类码**（cs.LG、math.AP……），可以做
精确映射。映射数据在 ``data/infohub_topic_mapping_data.xml``，共 161 条。

命中不到映射时归到「其他」兜底，而不是留空——留空会让条目在按学科订阅的时间线里
彻底消失。
"""

import logging

from odoo.addons.component.core import Component

_logger = logging.getLogger(__name__)

#: 本 classifier 在 infohub.topic.mapping 里的 provider 作用域
MAPPING_PROVIDER = "arxiv"


class ArxivClassifier(Component):
    _name = "infohub.classifier.arxiv"
    _inherit = "infohub.classifier.base"
    _provider = "arxiv"
    _medium = None

    def classify(self, item, entry):
        codes = self._category_codes(entry)
        if not codes:
            return False

        topics = self.env["infohub.topic.mapping"].resolve(MAPPING_PROVIDER, codes)

        if not topics:
            # 兜底：新分类码还没进映射表时，退一级到 archive（cs.XX -> cs）
            archives = {code.split(".")[0] for code in codes if "." in code}
            if archives:
                topics = self.env["infohub.topic.mapping"].resolve(
                    MAPPING_PROVIDER, sorted(archives)
                )
            if not topics:
                _logger.info(
                    "InfoHub arXiv：分类码 %s 没有对应映射，归到「其他」", codes
                )
                fallback = self.env.ref("infohub.topic_other", raise_if_not_found=False)
                if fallback:
                    topics = fallback

        if not topics:
            return False

        item.topic_ids = [(4, topic.id) for topic in topics]
        if not item.primary_topic_id:
            # 主分类码是 arXiv 给的第一个，对应的学科作主学科
            primary = self.env["infohub.topic.mapping"].resolve(
                MAPPING_PROVIDER, codes[:1]
            )
            item.primary_topic_id = (primary or topics)[0]
        return True

    @staticmethod
    def _category_codes(entry):
        """取出 arXiv 分类码，主分类排在最前，去重保序。

        feedparser 把 ``<arxiv:primary_category>`` 放进 ``arxiv_primarycategory``，
        把全部 ``<category>`` 放进 ``tags``。
        """
        codes = []
        primary = entry.get("arxiv_primarycategory")
        if isinstance(primary, dict):
            primary = primary.get("term")
        if primary:
            codes.append(str(primary).strip())

        for tag in entry.get("tags") or []:
            term = tag.get("term") if isinstance(tag, dict) else tag
            if not term:
                continue
            code = str(term).strip()
            if code and code not in codes:
                codes.append(code)
        return codes
