"""网页采集的通用 mapper —— ``(provider = generic, transport = web)``。

同时声明两个匹配键，与 ``infohub_rss`` 的 ``(generic, rss)`` 天然不撞（ADR-007）。

职责：把传输产出的 HTML 用配置里的选择器提取成字段。选择器提取放在 mapper 而不是
transport，是因为"怎么把一个单元变成字段"属于映射；transport 只负责"把字节切成单元"。
这与 RSS 那边的分工一致（RSS 传输用 feedparser 切出 entries，mapper 映射字段）。
"""

import logging

from bs4 import BeautifulSoup
from dateutil import parser as date_parser

from odoo.addons.component.core import Component
from odoo.tools import html2plaintext
from odoo.tools.mail import html_sanitize

_logger = logging.getLogger(__name__)

PARSER = "lxml"

#: 摘要没有专门选择器时，从正文纯文本里截取这么长
SUMMARY_FALLBACK_LENGTH = 300


class WebMapper(Component):
    _name = "infohub.mapper.web"
    _inherit = "infohub.mapper.base"
    _provider = "generic"
    _transport = "web"

    def map(self, entry):
        profile = self.source.web_profile_id
        soup = BeautifulSoup(entry.get("html") or "", PARSER)

        # 先剔噪声再提字段：否则广告位里的 <h1> 可能被当成标题
        self._strip_noise(soup, profile)

        url = entry.get("url")
        content_html = self._content(soup, profile)
        content_text = html2plaintext(content_html) if content_html else ""

        return {
            # URL 同时作为源内身份：核心的 UNIQUE(source_id, external_id) 与传输的
            # "剔除已入库链接"都依赖这一点
            "external_id": url,
            "url": url,
            "title": self._title(soup, profile),
            "author_name": self._author(soup, profile),
            "published_at": self._published_at(soup, profile),
            "content": content_html,
            "content_text": content_text or None,
            "summary": self._summary(soup, profile, content_text),
            "lang": self._lang(soup),
        }

    # ------------------------------------------------------------------
    @staticmethod
    def _strip_noise(soup, profile):
        """删除配置里指定的噪声节点，外加脚本与样式。

        ``<script>`` / ``<style>`` 无条件删除：它们的文本会污染正文提取结果，
        而 html_sanitize 是在之后才做的。
        """
        for tag in soup.find_all(["script", "style", "noscript"]):
            tag.decompose()
        for selector in profile.strip_selector_list():
            for node in soup.select(selector):
                node.decompose()

    @staticmethod
    def _text(soup, selector):
        """按选择器取文本，压缩空白。"""
        if not selector:
            return None
        node = soup.select_one(selector)
        if node is None:
            return None
        return " ".join(node.get_text(" ", strip=True).split()) or None

    def _title(self, soup, profile):
        title = self._text(soup, profile.title_selector)
        if not title:
            # 退回页面 <title>
            if soup.title and soup.title.string:
                title = " ".join(str(soup.title.string).split())
        return (title or "")[:512] or None

    def _author(self, soup, profile):
        author = self._text(soup, profile.author_selector)
        return (author or "")[:256] or None

    def _content(self, soup, profile):
        """提取正文并净化。

        第三方 HTML 会渲染到 website 公开页面，``html_sanitize`` 是硬要求（N4）。
        """
        if not profile.content_selector:
            return None
        node = soup.select_one(profile.content_selector)
        if node is None:
            return None
        return html_sanitize(str(node)) or None

    def _summary(self, soup, profile, content_text):
        summary = self._text(soup, profile.summary_selector)
        if summary:
            return html_sanitize(f"<p>{summary}</p>")
        if content_text:
            # 没有专门的摘要选择器时，从正文截一段
            snippet = content_text[:SUMMARY_FALLBACK_LENGTH].rstrip()
            if len(content_text) > SUMMARY_FALLBACK_LENGTH:
                snippet += "…"
            return html_sanitize(f"<p>{snippet}</p>")
        return None

    def _published_at(self, soup, profile):
        """提取发布时间。

        优先读 ``datetime`` 属性（``<time datetime="2026-08-30">``）——那是机器可读的
        规范格式；没有再读文本。
        """
        if not profile.date_selector:
            return None
        node = soup.select_one(profile.date_selector)
        if node is None:
            return None

        raw = (
            node.get("datetime")
            or node.get("content")
            or " ".join(node.get_text(" ", strip=True).split())
        )
        if not raw:
            return None

        try:
            if profile.date_format:
                from datetime import datetime

                return datetime.strptime(raw.strip(), profile.date_format)
            # dateutil 能认大多数常见写法；中文日期需要在配置里显式给格式
            parsed = date_parser.parse(raw, fuzzy=True)
            # 落库要 naive UTC：带时区的先转 UTC 再去掉 tzinfo
            if parsed.tzinfo is not None:
                from datetime import timezone

                parsed = parsed.astimezone(timezone.utc).replace(tzinfo=None)
            return parsed
        except (ValueError, OverflowError, date_parser.ParserError) as exc:
            _logger.info(
                "InfoHub 网页采集：日期 %r 解析失败（格式=%r）：%s",
                raw,
                profile.date_format,
                exc,
            )
            return None

    @staticmethod
    def _lang(soup):
        """从 <html lang="..."> 取语言。"""
        html_tag = soup.find("html")
        if html_tag:
            lang = html_tag.get("lang")
            if lang:
                return str(lang)[:16]
        return None
