"""arXiv 条目映射。

匹配键是 ``(provider=arxiv, transport=arxiv_api)``——两个都声明，保证与其他 mapper
不冲突（ADR-007）。

产出的 payload 里除了 ``infohub.item`` 的字段，还带上论文介质要用的键
（``arxiv_id`` / ``doi`` / ``abstract`` / ``author_names`` / ``pdf_url`` /
``journal_name`` / ``published_version``）。核心的 ``_item_vals`` 会按字段白名单把这些
额外键过滤掉，介质 component 的 ``payload_vals`` 再来消费它们——**mapper 不需要知道
载荷表长什么样**。
"""

import calendar
import logging
from datetime import datetime

from markupsafe import Markup, escape

from odoo.addons.component.core import Component

_logger = logging.getLogger(__name__)


class ArxivMapper(Component):
    _name = "infohub.mapper.arxiv"
    _inherit = "infohub.mapper.base"
    _provider = "arxiv"
    _transport = "arxiv_api"

    def map(self, entry):
        abstract = self._abstract_text(entry)
        arxiv_id = self._arxiv_id(entry)

        vals = {
            # --- infohub.item 字段 ---
            "external_id": arxiv_id or entry.get("id") or None,
            "title": self._title(entry),
            "url": self._abs_url(entry) or entry.get("link") or None,
            "author_name": self._first_author(entry),
            "published_at": self._published_at(entry),
            "lang": "en",
            "raw_data": self._raw(entry),
            # 摘要放进 item.summary 供列表页展示。arXiv 的摘要是纯文本，
            # 要转义后再包 <p>，否则里面的 < > & 会破坏 HTML
            "summary": self._abstract_html(abstract),
            # --- 论文介质要用的键（由 payload_vals 消费）---
            "arxiv_id": arxiv_id,
            "doi": entry.get("arxiv_doi") or None,
            "abstract": abstract,
            "author_names": self._authors(entry),
            "pdf_url": self._pdf_url(entry),
            "journal_name": entry.get("arxiv_journal_ref") or None,
            # 有 journal_ref 说明已被期刊接收/发表，否则是预印本
            "published_version": (
                "published" if entry.get("arxiv_journal_ref") else "preprint"
            ),
        }
        return vals

    # ------------------------------------------------------------------
    @staticmethod
    def _title(entry):
        title = entry.get("title")
        if not title:
            return None
        # arXiv 的标题带换行与缩进
        return " ".join(str(title).split())[:512] or None

    @staticmethod
    def _abstract_text(entry):
        """提取论文摘要（纯文本）。

        注意方法名不叫 ``_abstract``：那是 component 框架用来判断"组件是否抽象"的
        **类属性**（``AbstractComponent._abstract``）。定义同名方法会把它从布尔值
        覆盖成函数对象，函数是真值，于是 ``ComponentRegistry.lookup`` 会把这个
        component 当成抽象组件直接排除——表现为"明明写了 mapper 却报
        NoComponentError"，非常难查。
        """
        summary = entry.get("summary")
        if not summary:
            return None
        return " ".join(str(summary).split()) or None

    @staticmethod
    def _abstract_html(abstract):
        """把纯文本摘要包成 HTML。

        必须转义：摘要里的数学符号常含 ``<`` ``>`` ``&``，不转义会破坏页面结构。
        用 markupsafe 的 escape + Markup，与 Odoo 官方模块（mail_render_mixin 等）
        一致；``odoo.tools.misc.html_escape`` 只是 ``markupsafe.escape`` 的别名。
        """
        if not abstract:
            return None
        return Markup("<p>%s</p>") % escape(abstract)

    @staticmethod
    def _arxiv_id(entry):
        """从 Atom id 里取 arXiv ID。

        形如 ``http://arxiv.org/abs/2401.12345v1``，取最后一段。版本号由论文模型的
        归一化函数去掉。
        """
        raw = entry.get("id") or ""
        if "/abs/" not in raw:
            return None
        return raw.rsplit("/abs/", 1)[1] or None

    @staticmethod
    def _abs_url(entry):
        raw = entry.get("id") or ""
        return raw if raw.startswith("http") else None

    @staticmethod
    def _pdf_url(entry):
        """从 links 里找 PDF 链接。只存链接，不下载（R11.2）。"""
        for link in entry.get("links") or []:
            if not isinstance(link, dict):
                continue
            if link.get("type") == "application/pdf" or link.get("title") == "pdf":
                return link.get("href") or None
        return None

    @staticmethod
    def _authors(entry):
        names = []
        for author in entry.get("authors") or []:
            name = author.get("name") if isinstance(author, dict) else author
            if name:
                cleaned = " ".join(str(name).split())
                if cleaned and cleaned not in names:
                    names.append(cleaned)
        return names

    def _first_author(self, entry):
        names = self._authors(entry)
        if not names:
            return None
        # item.author_name 是单值字段，列表页展示第一作者就够了；
        # 完整作者列表在论文载荷的 author_ids 里
        label = names[0]
        if len(names) > 1:
            label = f"{label} 等"
        return label[:256]

    @staticmethod
    def _published_at(entry):
        for key in ("published_parsed", "updated_parsed"):
            value = entry.get(key)
            if not value:
                continue
            try:
                return datetime.utcfromtimestamp(calendar.timegm(value))
            except (ValueError, OverflowError, TypeError):
                continue
        return None

    @staticmethod
    def _raw(entry):
        """转成可 JSON 序列化的 dict。

        feedparser 会塞 ``time.struct_time`` 等非 JSON 类型，直接存会让
        ``fields.Json`` 写入失败。
        """
        raw = {}
        for key, value in dict(entry).items():
            if isinstance(value, (str, int, float, bool)) or value is None:
                raw[key] = value
            elif isinstance(value, (list, tuple)):
                raw[key] = [
                    item if isinstance(item, (str, int, float, bool)) else str(item)
                    for item in value
                ]
            elif isinstance(value, dict):
                raw[key] = {
                    str(k): (v if isinstance(v, (str, int, float, bool)) else str(v))
                    for k, v in value.items()
                }
            else:
                raw[key] = str(value)
        return raw
