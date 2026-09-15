"""``article`` 介质 —— 核心默认介质，覆盖新闻与博客文章。

article 没有额外的载荷表：它需要的字段（标题、正文、作者、发布时间）已经全在
``infohub.item`` 的核心字段里。论文、社交这类有独立结构化数据的介质才需要
载荷表（见 ``infohub.medium.payload``）。

去重身份策略：优先用源提供的 GUID，没有则退回规范化 URL。规范化会剥掉
跟踪参数，这样同一篇文章带着不同 utm_source 从两个源进来能收敛为一条。
"""

from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from odoo.addons.component.core import Component

#: 需要从 URL 中剥离的跟踪参数前缀与全名。
#: 同一篇文章常常带着不同的跟踪参数从多个渠道进来，不剥掉就无法收敛。
TRACKING_PREFIXES = ("utm_",)
TRACKING_PARAMS = frozenset(
    {
        "fbclid",
        "gclid",
        "dclid",
        "msclkid",
        "igshid",
        "mc_cid",
        "mc_eid",
        "ref",
        "ref_src",
        "spm",
        "share_token",
        "from",
    }
)


def normalize_url(url):
    """规范化 URL，用于跨源去重。

    * scheme 与 host 转小写，去掉默认端口
    * 丢弃 fragment
    * 剥离跟踪参数，其余查询参数按键排序
    * 去掉末尾斜杠
    """
    if not url:
        return None

    parts = urlsplit(url.strip())
    if not parts.netloc:
        return url.strip() or None

    scheme = parts.scheme.lower() or "https"
    host = (parts.hostname or "").lower()
    port = parts.port
    if port and not (
        (scheme == "http" and port == 80) or (scheme == "https" and port == 443)
    ):
        host = f"{host}:{port}"

    query_pairs = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if key.lower() not in TRACKING_PARAMS
        and not any(key.lower().startswith(prefix) for prefix in TRACKING_PREFIXES)
    ]
    query = urlencode(sorted(query_pairs))

    path = parts.path.rstrip("/") or "/"

    return urlunsplit((scheme, host, path, query, ""))


class ArticleMedium(Component):
    """文章介质。"""

    _name = "infohub.medium.article"
    _inherit = "infohub.medium.base"
    _medium = "article"
    _payload_model = None  # 无额外载荷表

    def identity(self, payload):
        """GUID 优先，其次规范化 URL。"""
        guid = (payload.get("external_id") or "").strip()
        if guid:
            return guid
        return normalize_url(payload.get("url"))
