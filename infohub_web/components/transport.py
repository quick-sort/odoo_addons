"""网页选择器传输：两阶段抓取。

阶段一：按分页方式翻列表页，用 CSS 选择器取出条目链接
阶段二：逐个抓详情页

只抓新的（关键的成本控制）
--------------------------
翻完列表页后，先把**已入库的链接剔除**，再去抓详情页。没有这一步，每轮都会把所有
详情页重抓一遍——这是网页采集与 RSS 最大的成本差异：RSS 一次请求拿到全部条目，
网页采集是每条一次请求。

安全
----
* 所有出网都走核心的 ``infohub.http``，因此每个 URL（含从页面里抓到的详情页链接）
  都会过一遍 SSRF 校验。这一点在网页采集里格外重要：详情页链接来自被抓取的页面，
  是**外部可影响的输入**，站点被攻破或页面被注入就可能出现指向内网的链接。
* ``same_host_only`` 默认开启，进一步把跟随范围限制在同域。
* 详情页之间按 ``min_request_interval`` 休眠，避免把来源站打崩。
"""

import logging
import time
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

from odoo import _
from odoo.addons.component.core import Component
from odoo.exceptions import UserError

from odoo.addons.infohub.url_guard import UrlNotAllowed

_logger = logging.getLogger(__name__)

#: bs4 的解析器。lxml 容错好且快，容器已自带
PARSER = "lxml"


class WebTransport(Component):
    _name = "infohub.transport.web"
    _inherit = "infohub.transport.base"
    _transport = "web"

    # ==================================================================
    def fetch(self):
        source = self.source
        profile = source.web_profile_id
        if not profile:
            raise UserError(_("源「%s」没有指定网页采集配置。", source.display_name))
        if profile.render_js:
            # 明确报错而不是静默抓到一个空壳页面
            raise UserError(
                _(
                    "采集配置「%s」勾选了「需要 JS 渲染」，但该能力尚未实现。"
                    "请为该站点另写渠道模块，或取消勾选（会抓到未渲染的 HTML）。",
                    profile.name,
                )
            )

        cursor = dict(source.cursor_state or {})
        http = self.component(usage="http")

        links, list_nodes, list_cursor = self._collect_links(http, profile, cursor)
        cursor.update(list_cursor)

        if not links:
            return [], cursor

        # 阶段间的关键一步：剔除已入库的链接
        fresh = self._filter_known(links)
        _logger.info(
            "InfoHub 网页采集：源 %s 列表页共 %s 条链接，其中 %s 条是新的",
            source.display_name,
            len(links),
            len(fresh),
        )
        if not fresh:
            return [], cursor

        limit = max(profile.max_items_per_run or 50, 1)
        fresh = fresh[:limit]

        if profile.detail_mode == "list_only":
            # 列表页自带全文：不再出网，直接用列表项的片段
            return [
                {"url": url, "html": list_nodes.get(url, ""), "from_list": True}
                for url in fresh
            ], cursor

        return self._fetch_details(http, fresh, source), cursor

    # ==================================================================
    # 阶段一：列表页
    # ==================================================================
    def _collect_links(self, http, profile, cursor):
        """翻列表页收集条目链接。

        :return: ``(links, list_nodes, cursor_update)``
            ``links`` 保序去重；``list_nodes`` 是 url -> 列表项 HTML 片段
            （仅 list_only 模式用得上）
        """
        source = self.source
        links = []
        seen = set()
        list_nodes = {}
        cursor_update = {}
        interval = source.min_request_interval or 0.0

        page = profile.page_start or 1
        next_url = None

        for index in range(max(profile.max_pages or 1, 1)):
            if index and interval:
                time.sleep(interval)

            url = next_url or profile.list_url(source, page=page)

            # 只对第一页做条件请求：列表页变了才有必要继续
            etag = cursor.get("etag") if index == 0 else None
            last_modified = cursor.get("last_modified") if index == 0 else None
            response = http.get(url, etag=etag, last_modified=last_modified)
            if response is None:
                _logger.debug("InfoHub 网页采集：%s 返回 304，列表页未变", url)
                break
            if index == 0:
                cursor_update.update(http.cursor_headers(response))

            soup = BeautifulSoup(response.content, PARSER)
            base_url = response.url or url
            page_links = 0

            for node in soup.select(profile.item_link_selector):
                href = node.get(profile.link_attribute or "href")
                if not href:
                    continue
                absolute = self._absolutize(base_url, href, profile)
                if not absolute or absolute in seen:
                    continue
                seen.add(absolute)
                links.append(absolute)
                page_links += 1
                if profile.detail_mode == "list_only":
                    # 取包含该链接的列表项容器，字段选择器作用在它上面
                    container = self._list_item_container(node)
                    list_nodes[absolute] = str(container)

            if page_links == 0:
                # 这一页没抓到任何链接，再翻下去也没意义
                break

            if profile.pagination_mode == "none":
                break
            if profile.pagination_mode == "page_param":
                page += profile.page_step or 1
                next_url = None
            else:  # next_link
                next_node = soup.select_one(profile.next_link_selector)
                href = next_node.get("href") if next_node else None
                next_url = self._absolutize(base_url, href, profile) if href else None
                if not next_url:
                    break

        return links, list_nodes, cursor_update

    def _absolutize(self, base_url, href, profile):
        """相对链接转绝对，并按需限制同域。"""
        href = (href or "").strip()
        if not href or href.startswith(("#", "javascript:", "mailto:", "tel:")):
            return None
        absolute = urljoin(base_url, href)
        if not absolute.lower().startswith(("http://", "https://")):
            return None
        if profile.same_host_only:
            if urlsplit(absolute).hostname != urlsplit(base_url).hostname:
                return None
        # 丢掉锚点：同一页的不同锚点是同一个条目
        return absolute.split("#", 1)[0]

    @staticmethod
    def _list_item_container(node):
        """从链接节点往上找列表项容器。

        list_only 模式下字段选择器要作用在"一个列表项"上，而选中的是链接本身。
        往上找最近的 article / li，找不到就退回父节点——比硬编码层数稳。
        """
        for parent in node.parents:
            if parent.name in ("article", "li"):
                return parent
        return node.parent or node

    # ==================================================================
    # 去重：剔除已入库的链接
    # ==================================================================
    def _filter_known(self, links):
        """剔除本源下已入库的链接。

        用 ``external_id`` 比对——mapper 把 URL 作为 external_id，核心的
        ``UNIQUE(source_id, external_id)`` 也依赖它。一次查询解决，不逐个查。
        """
        if not links:
            return []
        rows = self.env["infohub.item"].search_read(
            [("source_id", "=", self.source.id), ("external_id", "in", links)],
            ["external_id"],
        )
        known = {row["external_id"] for row in rows}
        return [url for url in links if url not in known]

    # ==================================================================
    # 阶段二：详情页
    # ==================================================================
    def _fetch_details(self, http, urls, source):
        """逐个抓详情页。单条失败不影响其余。"""
        interval = source.min_request_interval or 0.0
        entries = []
        for index, url in enumerate(urls):
            if index and interval:
                time.sleep(interval)
            try:
                response = http.get(url)
            except UrlNotAllowed as exc:
                # 详情页链接来自被抓取的页面，是外部可影响的输入
                _logger.warning(
                    "InfoHub 网页采集：详情页 %s 未通过安全校验，跳过：%s", url, exc
                )
                continue
            except Exception as exc:  # noqa: BLE001 - 网络错误形态太多
                _logger.info(
                    "InfoHub 网页采集：抓取详情页 %s 失败，跳过：%s: %s",
                    url,
                    type(exc).__name__,
                    exc,
                )
                continue
            if response is None:
                continue
            entries.append(
                {"url": response.url or url, "html": response.text, "from_list": False}
            )
        return entries
