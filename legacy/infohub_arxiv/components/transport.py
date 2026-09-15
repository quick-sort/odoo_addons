"""arXiv API 传输。

arXiv 的 ``/api/query`` 返回 Atom，用 feedparser 解析。与 ``infohub_rss`` 用同一个库
但不依赖那个模块——它提供的是 ``rss`` 传输，与本模块无关。

增量策略
--------
arXiv 不支持条件请求（无 ETag / Last-Modified），所以走**发布时间水位线**：
按 ``submittedDate`` 降序翻页，一旦遇到不新于游标的条目就停止翻页。这样稳定状态下
每轮只取到新增的那几条。

首轮（无游标）会翻到 ``arxiv_max_pages`` 页为止，剩下的留给下一轮——不在一个任务里
把历史全抓完。

限速
----
两层：
1. 任务级——本源的任务派到容量 1 的 ``root.infohub.arxiv`` 通道，全局串行
2. 请求级——翻页之间 sleep ``min_request_interval``（默认取 arXiv 建议的 3 秒）
"""

import calendar
import logging
import time
from datetime import datetime
from urllib.parse import urlencode, urlsplit, urlunsplit, parse_qsl

import feedparser

from odoo.addons.component.core import Component

_logger = logging.getLogger(__name__)

#: arXiv 建议的最小请求间隔（秒），源上没配时用这个
DEFAULT_INTERVAL = 3.0


class ArxivTransport(Component):
    _name = "infohub.transport.arxiv"
    _inherit = "infohub.transport.base"
    _transport = "arxiv_api"

    def fetch(self):
        source = self.source
        cursor = dict(source.cursor_state or {})
        http = self.component(usage="http")

        watermark = cursor.get("last_published")
        page_size = max(source.arxiv_max_results or 100, 1)
        max_pages = max(source.arxiv_max_pages or 10, 1)
        interval = source.min_request_interval or DEFAULT_INTERVAL

        entries = []
        newest = watermark
        start = 0

        for page in range(max_pages):
            if page:
                # 翻页之间必须等：arXiv 对连续请求很敏感
                time.sleep(interval)

            url = self._page_url(source.endpoint, start, page_size)
            response = http.get(url)
            if response is None:
                break

            parsed = feedparser.parse(response.content)
            if parsed.bozo and not parsed.entries:
                raise ValueError(
                    f"解析 arXiv 响应失败：{parsed.get('bozo_exception') or '未知错误'}"
                )

            page_entries = list(parsed.entries)
            if not page_entries:
                break

            stop = False
            for entry in page_entries:
                stamp = self._entry_timestamp(entry)
                if watermark and stamp and stamp <= watermark:
                    # 结果按提交时间降序，遇到旧条目说明后面全是旧的
                    stop = True
                    break
                entries.append(entry)
                if stamp and (newest is None or stamp > newest):
                    newest = stamp

            if stop or len(page_entries) < page_size:
                break
            start += page_size
        else:
            _logger.info(
                "InfoHub arXiv：源 %s 达到单轮页数上限 %s，剩余留给下一轮",
                source.display_name,
                max_pages,
            )

        if newest:
            cursor["last_published"] = newest
        return entries, cursor

    # ------------------------------------------------------------------
    @staticmethod
    def _page_url(endpoint, start, max_results):
        """把分页参数并进端点，保留用户已填的查询参数。

        直接字符串拼 ``&start=`` 会在端点已带 ``?`` 或已带 start 时出错，所以走
        正规的 URL 拆解与重组。同时强制按提交时间降序——增量策略依赖这个顺序。
        """
        parts = urlsplit(endpoint or "")
        params = dict(parse_qsl(parts.query, keep_blank_values=True))
        params.update({
            "start": str(start),
            "max_results": str(max_results),
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        })
        return urlunsplit(
            (parts.scheme, parts.netloc, parts.path, urlencode(params), "")
        )

    @staticmethod
    def _entry_timestamp(entry):
        """条目的提交时间，返回 ISO 字符串以便存进 Json 游标。"""
        for key in ("published_parsed", "updated_parsed"):
            value = entry.get(key)
            if value:
                try:
                    return datetime.utcfromtimestamp(
                        calendar.timegm(value)
                    ).isoformat()
                except (ValueError, OverflowError, TypeError):
                    continue
        return None
