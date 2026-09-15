"""RSS 通用 mapper —— ``(provider = generic, transport = rss)``。

同时声明 provider 与 transport 两个匹配键，保证与其他通用 mapper（例如
``infohub_web`` 的 ``(generic, web)``）不冲突（ADR-007）。

将来的期刊渠道模块可以 ``_inherit`` 本 mapper 只覆盖需要的部分——这是**轴内**
继承，是允许的；跨轴继承才是设计错误。
"""

import calendar
import logging
from datetime import datetime

from odoo.addons.component.core import Component
from odoo.tools.mail import html_sanitize

_logger = logging.getLogger(__name__)


class RssMapper(Component):
    _name = "infohub.mapper.rss"
    _inherit = "infohub.mapper.base"
    _provider = "generic"
    _transport = "rss"

    def map(self, entry):
        vals = {
            "external_id": self._external_id(entry),
            "title": self._clean_title(entry.get("title")),
            "url": entry.get("link") or None,
            "author_name": self._author(entry),
            "published_at": self._published_at(entry),
            "lang": self._lang(entry),
            # 保留原始报文：解析规则改了之后可以不联网重跑归一化（R2.5）
            "raw_data": self._raw(entry),
        }

        summary, content = self._summary_and_content(entry)
        if summary:
            vals["summary"] = summary
        if content:
            vals["content"] = content
        return vals

    # ------------------------------------------------------------------
    @staticmethod
    def _external_id(entry):
        """源内身份。

        优先用 feed 提供的 guid/id；没有则退回链接。两者都没有时返回 None，
        此时跨源去重会由介质按规范化 URL 兜底。
        """
        for key in ("id", "guid"):
            value = entry.get(key)
            if value:
                return str(value)[:512]
        link = entry.get("link")
        return str(link)[:512] if link else None

    @staticmethod
    def _clean_title(title):
        if not title:
            return None
        # feed 标题偶尔带换行与多余空白，落库前压平
        return " ".join(str(title).split())[:512] or None

    @staticmethod
    def _author(entry):
        author = entry.get("author")
        if not author and entry.get("authors"):
            first = entry["authors"][0]
            author = first.get("name") if isinstance(first, dict) else first
        if not author:
            detail = entry.get("author_detail") or {}
            author = detail.get("name")
        return str(author)[:256] if author else None

    @staticmethod
    def _published_at(entry):
        for key in ("published_parsed", "updated_parsed", "created_parsed"):
            value = entry.get(key)
            if not value:
                continue
            try:
                return datetime.utcfromtimestamp(calendar.timegm(value))
            except (ValueError, OverflowError, TypeError):
                continue
        return None

    def _lang(self, entry):
        lang = entry.get("language")
        if not lang:
            # 频道级语言由传输放进 WorkContext（很多 feed 只在频道级声明语言）
            lang = (getattr(self.work, "feed_meta", None) or {}).get("language")
        return str(lang)[:16] if lang else None

    @staticmethod
    def _summary_and_content(entry):
        """提取摘要与正文。

        RSS 的实践很乱：有的把全文放 ``description``，有的放
        ``content:encoded``，有的两者都有。策略是取最长的那份当正文，另一份
        当摘要——比信任字段名可靠。

        两者都经过 ``html_sanitize``：这是第三方 HTML，且会渲染到 website
        公开页面（N4）。
        """
        candidates = []
        summary = entry.get("summary")
        if summary:
            candidates.append(str(summary))
        for block in entry.get("content") or []:
            value = block.get("value") if isinstance(block, dict) else block
            if value:
                candidates.append(str(value))

        if not candidates:
            return None, None

        candidates.sort(key=len, reverse=True)
        content = html_sanitize(candidates[0])
        if len(candidates) == 1:
            # 只有一份内容时，作为摘要还是正文取决于长度：短的当摘要就够了
            if len(candidates[0]) < 500:
                return content, None
            return None, content
        return html_sanitize(candidates[-1]), content

    @staticmethod
    def _raw(entry):
        """把 feedparser 的条目转成可 JSON 序列化的 dict。

        feedparser 会塞入 ``time.struct_time`` 等非 JSON 类型，直接存会让
        ``fields.Json`` 写入失败，所以逐个字段做安全转换。
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
