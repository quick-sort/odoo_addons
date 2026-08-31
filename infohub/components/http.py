"""HTTP 客户端 component。

所有传输实现出网都必须经过这里，不要直接调 ``requests``（steering 里的安全
红线之一）。集中在一处的好处是 SSRF 防护、超时、响应体积上限、条件请求这四
件事只需要正确实现一次。

放在核心而不是单开传输模块的理由见 ADR-010：``infohub_rss``、``infohub_web``、
``infohub_arxiv`` 都要出网，而这些安全约束（N3/N5）本就是核心职责。
"""

import logging

import requests

from odoo import _
from odoo.addons.component.core import Component

from ..url_guard import UrlNotAllowed, allow_private_from_env, assert_url_allowed

_logger = logging.getLogger(__name__)

#: (连接超时, 读取超时)，秒
DEFAULT_TIMEOUT = (10, 30)

#: 响应体积上限，超过即中断并报错，防止一个巨大的 feed 打满 worker
DEFAULT_MAX_BYTES = 10 * 1024 * 1024

#: 重定向最大跳数。每一跳都要重新做 SSRF 校验
MAX_REDIRECTS = 5

DEFAULT_USER_AGENT = "Mozilla/5.0 (compatible; InfoHub/1.0; +Odoo)"


class ResponseTooLarge(Exception):
    """响应体积超过上限。"""


class InfohubHttp(Component):
    """带安全约束的 HTTP 客户端。

    用法::

        http = work.component(usage="http")
        response = http.get(url, etag=..., last_modified=...)
        if response is None:
            return [], None          # 304，内容未变
    """

    _name = "infohub.http"
    _inherit = "infohub.base"
    _usage = "http"

    # ------------------------------------------------------------------
    # 公开接口
    # ------------------------------------------------------------------
    def get(
        self,
        url,
        headers=None,
        params=None,
        timeout=None,
        max_bytes=DEFAULT_MAX_BYTES,
        etag=None,
        last_modified=None,
    ):
        """发起 GET 请求。

        :param str etag: 上一轮的 ETag，传入则带 ``If-None-Match``
        :param str last_modified: 上一轮的 Last-Modified，传入则带
            ``If-Modified-Since``
        :return: ``requests.Response``；服务端返回 304 时返回 ``None``
            （表示内容未变，调用方应直接结束本轮）
        :raise UrlNotAllowed: URL 未通过安全校验
        :raise ResponseTooLarge: 响应体积超限
        """
        request_headers = {"User-Agent": DEFAULT_USER_AGENT}
        if etag:
            request_headers["If-None-Match"] = etag
        if last_modified:
            request_headers["If-Modified-Since"] = last_modified
        if headers:
            request_headers.update(headers)

        response = self._request(
            "GET",
            url,
            headers=request_headers,
            params=params,
            timeout=timeout or DEFAULT_TIMEOUT,
            max_bytes=max_bytes,
        )
        if response.status_code == 304:
            _logger.debug("InfoHub: %s 返回 304，内容未变", url)
            return None
        response.raise_for_status()
        return response

    def cursor_headers(self, response):
        """从响应中提取下一轮条件请求要用的游标。

        :return: dict，可能含 ``etag`` 与 ``last_modified``，可直接并入
            ``source.cursor_state``
        """
        cursor = {}
        if response is None:
            return cursor
        etag = response.headers.get("ETag")
        if etag:
            cursor["etag"] = etag
        last_modified = response.headers.get("Last-Modified")
        if last_modified:
            cursor["last_modified"] = last_modified
        return cursor

    # ------------------------------------------------------------------
    # 内部实现
    # ------------------------------------------------------------------
    def _allow_private(self):
        return allow_private_from_env(self.env)

    def _request(self, method, url, headers, params, timeout, max_bytes):
        """手工跟随重定向，**每一跳都做 SSRF 校验**。

        不能用 requests 的 ``allow_redirects=True``：那样只校验了首个 URL，
        攻击者可以用一个公网 URL 302 跳到 127.0.0.1 或云元数据服务地址。
        """
        allow_private = self._allow_private()
        current_url = url
        # params 只在第一跳生效；重定向的 Location 已包含完整查询串
        current_params = params

        for hop in range(MAX_REDIRECTS + 1):
            assert_url_allowed(current_url, allow_private=allow_private)

            response = requests.request(
                method,
                current_url,
                headers=headers,
                params=current_params,
                timeout=timeout,
                allow_redirects=False,
                stream=True,
            )

            if response.is_redirect or response.is_permanent_redirect:
                location = response.headers.get("Location")
                response.close()
                if not location:
                    raise UrlNotAllowed(
                        _("%s 返回重定向但没有 Location 头。", current_url)
                    )
                # 相对 Location 要拼成绝对 URL 才能校验
                current_url = requests.compat.urljoin(current_url, location)
                current_params = None
                continue

            try:
                self._read_bounded(response, max_bytes)
            except ResponseTooLarge:
                response.close()
                raise
            return response

        raise UrlNotAllowed(
            _("%(url)s 的重定向超过 %(max)s 跳。", url=url, max=MAX_REDIRECTS)
        )

    def _read_bounded(self, response, max_bytes):
        """在体积上限内读完响应体。

        先看 Content-Length 快速失败，但不能只信它——它可能缺失或撒谎，所以
        边读边累计实际字节数。读完后把内容塞回 ``response._content``，让调用
        方仍能正常用 ``response.content`` / ``response.text``。
        """
        if max_bytes is None:
            response._content = response.raw.read()
            response._content_consumed = True
            return

        declared = response.headers.get("Content-Length")
        if declared and declared.isdigit() and int(declared) > max_bytes:
            raise ResponseTooLarge(
                _(
                    "%(url)s 声明的响应体积 %(size)s 字节超过上限 %(max)s。",
                    url=response.url,
                    size=declared,
                    max=max_bytes,
                )
            )

        chunks = []
        total = 0
        for chunk in response.iter_content(chunk_size=64 * 1024):
            if not chunk:
                continue
            total += len(chunk)
            if total > max_bytes:
                raise ResponseTooLarge(
                    _(
                        "%(url)s 的响应体积超过上限 %(max)s 字节。",
                        url=response.url,
                        max=max_bytes,
                    )
                )
            chunks.append(chunk)

        response._content = b"".join(chunks)
        response._content_consumed = True
