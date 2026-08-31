"""正文提取 enricher。

用 ``many_components(usage='enricher')`` 被取到，所以本模块和 ``infohub_llm``
可以各挂一个、互不知晓。

提取用 trafilatura：它会剥掉导航、广告、推荐位、评论区，只留正文，比自己写选择器
稳得多。输出要 HTML（``output_format='html'``）而不是纯文本，否则段落、列表、
代码块全丢了。

安全：
* 出网走核心的 ``infohub.http``，自动继承 SSRF 防护、超时、体积上限
* 提取结果经 ``html_sanitize``——trafilatura 会去掉脚本，但净化是我们自己的底线，
  不把安全性外包给第三方库
"""

import logging
import time

import trafilatura

from odoo import _
from odoo.addons.component.core import Component
from odoo.tools import html2plaintext
from odoo.tools.mail import html_sanitize

from odoo.addons.infohub.url_guard import UrlNotAllowed

_logger = logging.getLogger(__name__)

#: 单次任务最多处理多少条，避免一个任务跑太久被 worker 超时杀掉
BATCH_LIMIT = 50

#: 提取出的正文短于这个长度就认为失败（多半是拿到了付费墙或反爬页面）
MIN_ACCEPTABLE_LENGTH = 200


class FulltextEnricher(Component):
    _name = "infohub.enricher.fulltext"
    _inherit = "infohub.enricher.base"
    #: 不限介质与来源：任何有 url 且正文过短的条目都适用
    _provider = None
    _medium = None

    @classmethod
    def _component_match(cls, work, usage=None, model_name=None, **kw):
        source = cls._work_source(work)
        return bool(source) and source.fulltext_enabled

    # ------------------------------------------------------------------
    def enrich(self, items):
        """为需要正文的条目抓取并提取原文。"""
        candidates = self._candidates(items)
        if not candidates:
            return True

        http = self.component(usage="http")
        interval = self.source.min_request_interval or 0.0
        processed = 0

        for item in candidates[:BATCH_LIMIT]:
            if processed and interval:
                # 遵守来源方限速：连续抓原文比抓 feed 更容易触发封禁
                time.sleep(interval)
            self._extract_one(item, http)
            processed += 1

        remaining = len(candidates) - processed
        if remaining > 0:
            # 剩下的下一轮再处理，不在一个任务里做完
            _logger.info(
                "InfoHub 正文提取：源 %s 还有 %s 条待处理，留给下一轮",
                self.source.display_name,
                remaining,
            )
        return True

    def _candidates(self, items):
        """筛出真正需要抓原文的条目。

        三个条件：待处理、有 url、现有正文短于阈值。
        """
        threshold = self.source.fulltext_min_length or 0
        return items.filtered(
            lambda item: item.fulltext_state == "pending"
            and item.url
            and len(item.content_text or "") < threshold
        )

    def _extract_one(self, item, http):
        """抓取并提取单个条目的正文。

        任何失败都记录在条目上并继续下一条——一个来源站挂掉不该让整批增强失败。
        """
        try:
            response = http.get(item.url)
        except UrlNotAllowed as exc:
            # URL 指向内网或协议不允许：这是配置/数据问题，不是临时故障
            return self._mark_failed(item, _("URL 未通过安全校验：%s", exc))
        except Exception as exc:  # noqa: BLE001 - 网络错误形态太多，统一记录
            return self._mark_failed(item, f"{type(exc).__name__}: {exc}")

        if response is None:
            # 304：抓原文不带条件请求，正常不会走到这里
            return self._mark_failed(item, _("来源返回 304，未取到内容。"))

        try:
            extracted = trafilatura.extract(
                response.text,
                url=item.url,
                output_format="html",
                include_comments=False,
                include_tables=True,
                include_formatting=True,
                include_links=True,
                favor_precision=True,
            )
        except Exception as exc:  # noqa: BLE001 - 第三方解析器，异常形态不可控
            return self._mark_failed(item, f"提取失败 {type(exc).__name__}: {exc}")

        if not extracted:
            return self._mark_failed(item, _("未能从页面中识别出正文。"))

        # 净化是我们自己的底线，不把安全性外包给第三方库
        content = html_sanitize(extracted)
        text = html2plaintext(content) if content else ""

        if len(text) < MIN_ACCEPTABLE_LENGTH:
            # 多半拿到了付费墙、同意 cookie 页或反爬页面
            return self._mark_failed(
                item,
                _("提取到的正文过短（%s 字符），可能是付费墙或反爬页面。", len(text)),
            )

        item.write(
            {
                "content": content,
                "content_text": text,
                "fulltext_state": "done",
                "fulltext_error": False,
                "fulltext_length": len(text),
            }
        )
        _logger.debug(
            "InfoHub 正文提取：条目 %s 提取到 %s 字符", item.id, len(text)
        )
        return True

    @staticmethod
    def _mark_failed(item, message):
        item.write({"fulltext_state": "failed", "fulltext_error": message})
        _logger.info("InfoHub 正文提取失败：条目 %s —— %s", item.id, message)
        return False
