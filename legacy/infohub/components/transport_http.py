"""通用 HTTP 传输。

核心自带这一个传输实现，因为核心本来就拥有 HTTP 客户端（ADR-010）。它适用于
"一个端点返回 JSON"这类朴素 API：拉取端点、做条件请求、把响应拆成条目交给
mapper。

**核心不提供与之配套的通用 mapper**——怎么把 JSON 字段映射成条目字段是来源方
特有的，属于 provider 维度。所以 ``(medium, http, generic)`` 这个组合会在
mapper 上解析失败，这是预期行为：要么装一个提供通用 mapper 的传输模块
（``infohub_rss`` 提供 ``(generic, rss)``、``infohub_web`` 提供 ``(generic, web)``），
要么自己写一个 provider mapper 配 ``transport = http``。

条目拆分规则
------------
* 响应是 JSON 数组 → 数组元素即条目
* 响应是 JSON 对象且含常见的列表字段（``items`` / ``data`` / ``results`` /
  ``records`` / ``entries``）→ 该列表的元素即条目
* 响应是其他 JSON 对象 → 整个对象作为单个条目
* 不是 JSON → 单个条目 ``{"text": ..., "content": ..., "url": ...}``，
  由 provider mapper 自行解析
"""

import json
import logging

from odoo.addons.component.core import Component

_logger = logging.getLogger(__name__)

#: JSON 对象里常见的列表字段名，按顺序探测
LIST_KEYS = ("items", "data", "results", "records", "entries")


class HttpTransport(Component):
    """通用 HTTP 传输。"""

    _name = "infohub.transport.http"
    _inherit = "infohub.transport.base"
    _transport = "http"

    def fetch(self):
        source = self.source
        cursor = dict(source.cursor_state or {})
        http = self.component(usage="http")

        headers = source.credential_id.auth_headers()
        auth = source.credential_id.basic_auth()
        if auth:
            # requests 的 auth 参数不经过 headers，这里显式提示实现者
            _logger.debug(
                "InfoHub: 源 %s 使用 HTTP Basic 认证，交由 requests 处理", source.id
            )

        response = http.get(
            source.endpoint,
            headers=headers or None,
            etag=cursor.get("etag"),
            last_modified=cursor.get("last_modified"),
        )
        if response is None:
            # 304：内容未变，游标保持原样
            return [], None

        entries = self._split_entries(response)
        cursor.update(http.cursor_headers(response))
        return entries, cursor

    def _split_entries(self, response):
        """把响应拆成条目列表。规则见模块文档。"""
        try:
            payload = response.json()
        except (ValueError, json.JSONDecodeError):
            return [
                {
                    "text": response.text,
                    "content": response.content,
                    "url": response.url,
                }
            ]

        if isinstance(payload, list):
            return payload
        if isinstance(payload, dict):
            for key in LIST_KEYS:
                value = payload.get(key)
                if isinstance(value, list):
                    return value
            return [payload]
        return [{"value": payload, "url": response.url}]
