"""URL 安全校验（SSRF 防护）。

信息源的 URL 由用户输入，由服务端发起请求。若不加限制，任何能创建源的用户
都可以拿 Odoo 服务器去探测内网（云环境下还包括 169.254.169.254 这类元数据
服务）。这是本项目最主要的安全风险，见 requirements.md N3。

本模块独立于 component 层，因为 ``infohub.source`` 的字段约束也要用它——约束
在 create 阶段执行，那时三轴组合可能还不合法，无法解析 component。

残留风险
--------
本模块在请求前解析域名并校验所有解析结果，但无法完全消除 DNS rebinding：
攻击者控制的域名可以在校验通过之后、实际连接之前把解析结果改成内网地址。
彻底防御需要"连接到已校验的 IP 并手工设置 Host 头"，代价是破坏 TLS SNI 与
虚拟主机。当前实现接受这一残留风险，因为本项目的源由内部管理员创建，不是
任意匿名用户可控的输入。**若将来允许 portal 用户自建源，必须重新评估。**
"""

import ipaddress
import socket
from urllib.parse import urlsplit

from odoo import _
from odoo.exceptions import UserError

#: 允许的 URL scheme。file://、gopher://、ftp:// 等一律拒绝。
ALLOWED_SCHEMES = ("http", "https")

#: 不需要 DNS 就能判定为本机的主机名。保存时的快速校验用。
LOCAL_HOSTNAMES = frozenset(
    {"localhost", "localhost.localdomain", "ip6-localhost", "ip6-loopback"}
)

#: 允许绕过私网校验的开关（仅供开发与测试，生产环境不要开）。
ALLOW_PRIVATE_PARAM = "infohub.allow_private_urls"


class UrlNotAllowed(UserError):
    """URL 未通过安全校验。"""


def _is_blocked_ip(ip):
    """判断 IP 是否属于禁止访问的范围。

    比 ``is_private`` 单独判断更严：额外覆盖环回、链路本地（含云元数据服务的
    169.254.169.254）、保留段、组播与未指定地址，并对 IPv4-mapped IPv6 做拆解。
    """
    # ::ffff:10.0.0.1 这类映射地址要按内层 IPv4 判断，否则会绕过检查
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped:
        ip = ip.ipv4_mapped
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_reserved
        or ip.is_multicast
        or ip.is_unspecified
    )


def resolve_and_check(hostname, allow_private=False):
    """解析域名并校验全部解析结果。

    :return: 解析出的 IP 字符串列表
    :raise UrlNotAllowed: 解析失败，或任一结果落在禁止范围内
    """
    # 用户可能直接填 IP，此时不需要 DNS
    try:
        literal = ipaddress.ip_address(hostname)
    except ValueError:
        literal = None

    if literal is not None:
        addresses = [literal]
    else:
        try:
            infos = socket.getaddrinfo(hostname, None)
        except (socket.gaierror, UnicodeError) as exc:
            raise UrlNotAllowed(
                _("无法解析主机名 %(host)s：%(err)s", host=hostname, err=exc)
            ) from exc
        addresses = []
        for info in infos:
            try:
                addresses.append(ipaddress.ip_address(info[4][0]))
            except ValueError:
                continue
        if not addresses:
            raise UrlNotAllowed(_("主机名 %s 没有解析出有效地址。", hostname))

    if not allow_private:
        for ip in addresses:
            if _is_blocked_ip(ip):
                raise UrlNotAllowed(
                    _(
                        "拒绝访问 %(host)s：解析到受限地址 %(ip)s"
                        "（私网 / 环回 / 链路本地 / 保留段）。",
                        host=hostname,
                        ip=ip,
                    )
                )

    return [str(ip) for ip in addresses]


def assert_url_allowed(url, allow_private=False, resolve=True):
    """校验 URL 可以安全地发起请求。

    :param str url: 待校验的 URL
    :param bool allow_private: 是否允许私网地址（仅开发/测试）
    :param bool resolve: 是否做 DNS 解析并校验解析结果。

        ``resolve=False`` 用于**保存时**的字段校验：只查 scheme、主机名存在性、
        字面量 IP 与已知本机名，不发 DNS 请求。原因有两个：

        1. 在 ``@api.constrains`` 里发网络请求会让每次保存源都阻塞在 DNS 上，
           解析器慢或不可达时会拖住整个事务
        2. 保存时的解析结果并不能保证请求时仍然相同（DNS rebinding 本来就是
           已知的残留风险），所以保存时解析给不出真正的安全保证

        真正的防护点在**发起请求时**：``infohub.http`` component 对每一跳都用
        ``resolve=True`` 校验。安全属性因此不受影响——任何实际出网都被检查过。

    :raise UrlNotAllowed: scheme 不允许、缺主机名、或（resolve=True 时）解析到受限地址
    """
    if not url:
        raise UrlNotAllowed(_("URL 不能为空。"))

    parts = urlsplit(url.strip())
    if parts.scheme.lower() not in ALLOWED_SCHEMES:
        raise UrlNotAllowed(
            _(
                "只允许 %(allowed)s 协议，收到 %(scheme)r。",
                allowed="/".join(ALLOWED_SCHEMES),
                scheme=parts.scheme,
            )
        )
    hostname = parts.hostname
    if not hostname:
        raise UrlNotAllowed(_("URL 缺少主机名：%s", url))

    if not allow_private:
        # 不需要 DNS 就能判定的两类：已知本机名，以及字面量 IP
        lowered = hostname.lower()
        if lowered in LOCAL_HOSTNAMES or lowered.endswith(".localhost"):
            raise UrlNotAllowed(
                _("拒绝访问本机地址 %s。", hostname)
            )
        try:
            literal = ipaddress.ip_address(hostname)
        except ValueError:
            literal = None
        if literal is not None and _is_blocked_ip(literal):
            raise UrlNotAllowed(
                _("拒绝访问受限地址 %s（私网 / 环回 / 链路本地 / 保留段）。", hostname)
            )

    if resolve:
        resolve_and_check(hostname, allow_private=allow_private)
    return True


def allow_private_from_env(env):
    """读取"允许私网"开关。默认关闭。"""
    return (
        env["ir.config_parameter"]
        .sudo()
        .get_param(ALLOW_PRIVATE_PARAM, "False")
        .strip()
        .lower()
        in ("1", "true", "yes")
    )
