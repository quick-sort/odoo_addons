"""``paper`` 介质 component。

职责（介质轴，ADR-006）：
1. 计算**跨源去重身份** —— 论文的身份是 DOI，预印本是 arXiv ID
2. 把归一化数据落进 ``infohub.paper`` 载荷表

为什么身份计算在这里而不在各 provider
--------------------------------------
同一篇论文经 arXiv、期刊 RSS、Crossref 三条路进来，GUID 与 URL 完全不同，唯一稳定的
身份是 DOI。如果让每个 provider 各自实现去重，同一介质的 N 个来源会各写一份 DOI
归一化，且跨源收敛无法保证一致。

关键设计：从任意可用字段里捞 DOI
--------------------------------
``infohub_rss`` 的通用 mapper 不知道 DOI 是什么，它只会给出 title / url / summary。
所以 :meth:`identity` 在 mapper 没有显式给 ``doi`` 时，会从 url / 摘要 / 正文里用正则
捞 DOI 或 arXiv ID —— 期刊 RSS 通常在链接或描述里带 DOI。

**这让"一个期刊 RSS 源只要把 medium 设成 paper 就能参与论文去重"成为可能，
不需要为它写任何 provider 代码。** 这是把去重放在介质轴而非来源轴的直接收益。

找不到任何稳定身份时返回 None，即不参与跨源去重——宁可漏合并，不可错合并。
"""

import logging

from odoo.addons.component.core import Component

from ..models.infohub_paper import normalize_arxiv_id, normalize_doi

_logger = logging.getLogger(__name__)

#: 从自由文本里捞身份时，扫描的字段与顺序
IDENTITY_HAYSTACK_KEYS = ("url", "pdf_url", "summary", "abstract", "content_text")

#: 自由文本扫描的长度上限。摘要偶尔会很长，而 DOI 一定出现在靠前的位置
HAYSTACK_LIMIT = 20_000


class PaperMedium(Component):
    _name = "infohub.medium.paper"
    _inherit = "infohub.medium.base"
    _medium = "paper"
    _payload_model = "infohub.paper"

    # ==================================================================
    # 身份
    # ==================================================================
    def identity(self, payload):
        """计算跨源去重身份。

        优先级：显式 DOI → 显式 arXiv ID → 从自由文本捞 DOI → 从自由文本捞 arXiv ID。
        全部失败返回 None（不参与跨源去重）。
        """
        doi = normalize_doi(payload.get("doi"))
        if doi:
            return f"doi:{doi}"

        arxiv_id = normalize_arxiv_id(payload.get("arxiv_id"))
        if arxiv_id:
            return f"arxiv:{arxiv_id}"

        haystack = self._haystack(payload)
        if haystack:
            doi = normalize_doi(haystack)
            if doi:
                _logger.debug("InfoHub 论文：从自由文本捞到 DOI %s", doi)
                return f"doi:{doi}"
            arxiv_id = self._arxiv_from_url(payload.get("url"))
            if arxiv_id:
                return f"arxiv:{arxiv_id}"

        return None

    @staticmethod
    def _haystack(payload):
        """拼出用于正则扫描的文本。"""
        parts = []
        for key in IDENTITY_HAYSTACK_KEYS:
            value = payload.get(key)
            if value:
                parts.append(str(value))
        if not parts:
            return ""
        return " ".join(parts)[:HAYSTACK_LIMIT]

    @staticmethod
    def _arxiv_from_url(url):
        """只从 arxiv.org 的链接里认 arXiv ID。

        不对任意文本做 arXiv ID 匹配：``2401.12345`` 这种形态太容易和日期、
        编号、价格误撞，会造成错误合并。
        """
        if not url or "arxiv.org" not in str(url).lower():
            return None
        return normalize_arxiv_id(url)

    # ==================================================================
    # 载荷
    # ==================================================================
    def payload_vals(self, payload):
        """从归一化数据中提取论文载荷字段。

        作者与期刊在这里解析成记录：mapper 只需给出字符串（``author_names``
        列表、``journal_name``），不必关心模型。
        """
        vals = {
            "doi": payload.get("doi") or None,
            "arxiv_id": payload.get("arxiv_id") or None,
            "abstract": payload.get("abstract") or payload.get("summary_text") or None,
            "volume": payload.get("volume") or None,
            "issue": payload.get("issue") or None,
            "pages": payload.get("pages") or None,
            "pdf_url": payload.get("pdf_url") or None,
            "citation_count": payload.get("citation_count") or 0,
        }
        if payload.get("published_version"):
            vals["published_version"] = payload["published_version"]

        # mapper 没给显式 DOI 时，把从自由文本捞到的补上——否则载荷表里 DOI 是空的，
        # 而 identity 已经用它做过去重，两处不一致会让人困惑
        if not vals["doi"] and not vals["arxiv_id"]:
            recovered = self.identity(payload)
            if recovered and recovered.startswith("doi:"):
                vals["doi"] = recovered[4:]
            elif recovered and recovered.startswith("arxiv:"):
                vals["arxiv_id"] = recovered[6:]

        authors = payload.get("author_names")
        if authors:
            author_records = self.env["infohub.paper.author"].resolve(authors)
            vals["author_ids"] = [(6, 0, author_records.ids)]

        journal_name = payload.get("journal_name")
        if journal_name:
            journal = self.env["infohub.journal"].resolve(journal_name)
            if journal:
                vals["journal_id"] = journal.id

        return {key: value for key, value in vals.items() if value not in (None, False)}
