"""RSS / Atom 传输。

只负责"拿到字节并拆成 feed 条目"，字段映射交给 mapper（不同来源方可以复用同一
个传输却各有自己的 mapper）。

增量策略：优先用 HTTP 条件请求（ETag / Last-Modified）——命中 304 时整轮零解析。
服务端不支持条件请求时退回按发布时间过滤，游标里记住上一轮见过的最新发布时间。
"""

import calendar
import logging
from datetime import datetime

import feedparser

from odoo.addons.component.core import Component

_logger = logging.getLogger(__name__)


class RssTransport(Component):
    _name = "infohub.transport.rss"
    _inherit = "infohub.transport.base"
    _transport = "rss"

    def fetch(self):
        source = self.source
        cursor = dict(source.cursor_state or {})
        http = self.component(usage="http")

        response = http.get(
            source.endpoint,
            headers=source.credential_id.auth_headers() or None,
            etag=cursor.get("etag"),
            last_modified=cursor.get("last_modified"),
        )
        if response is None:
            _logger.debug("InfoHub RSS: %s 返回 304，无需解析", source.endpoint)
            return [], None

        # 传 bytes 而不是 text：feedparser 会自己按 XML 声明嗅探编码，比依赖
        # requests 从 Content-Type 猜的结果更准（很多 feed 的头部声明是错的）
        parsed = feedparser.parse(response.content)

        if parsed.bozo and not parsed.entries:
            # bozo 且没解析出任何条目才算失败；只要有条目就继续，
            # 现实中的 feed 极少完全合规
            raise ValueError(
                f"解析 feed 失败：{parsed.get('bozo_exception') or '未知错误'}"
            )
        if parsed.bozo:
            _logger.info(
                "InfoHub RSS: %s 的 feed 不完全合规但仍解析出 %s 条：%s",
                source.endpoint,
                len(parsed.entries),
                parsed.get("bozo_exception"),
            )

        entries = list(parsed.entries)
        last_seen = cursor.get("last_published")
        if last_seen and not (cursor.get("etag") or cursor.get("last_modified")):
            # 服务端不支持条件请求时的兜底增量
            entries = [
                entry
                for entry in entries
                if self._entry_timestamp(entry) is None
                or self._entry_timestamp(entry) > last_seen
            ]

        cursor.update(http.cursor_headers(response))
        newest = self._newest_timestamp(parsed.entries)
        if newest:
            cursor["last_published"] = newest

        # 频道级元数据通过 WorkContext 传给 mapper，**不要塞进游标**：
        # 游标是在整轮结束后才写回 source 的，mapper 在循环里读到的还是上一轮的
        # 旧游标，第一轮永远读不到。WorkContext 本就是为在 component 之间横向
        # 传递数据而设计的，且 transport 与 mapper 共享同一个 work 实例。
        self.work.feed_meta = {
            "language": (parsed.feed or {}).get("language"),
            "title": (parsed.feed or {}).get("title"),
            "link": (parsed.feed or {}).get("link"),
        }

        return entries, cursor

    # ------------------------------------------------------------------
    @staticmethod
    def _entry_timestamp(entry):
        """条目发布时间，返回 ISO 字符串以便存进 Json 游标。"""
        for key in ("published_parsed", "updated_parsed", "created_parsed"):
            value = entry.get(key)
            if value:
                try:
                    return datetime.utcfromtimestamp(
                        calendar.timegm(value)
                    ).isoformat()
                except (ValueError, OverflowError, TypeError):
                    continue
        return None

    def _newest_timestamp(self, entries):
        stamps = [self._entry_timestamp(entry) for entry in entries]
        stamps = [stamp for stamp in stamps if stamp]
        return max(stamps) if stamps else None
