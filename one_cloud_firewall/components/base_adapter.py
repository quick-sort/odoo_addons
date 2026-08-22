# Copyright 2026 Rui
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

from odoo.addons.component.core import AbstractComponent


def norm_cidr(cidr):
    """CIDR 归一化：去掉 /32 后缀，使 x.x.x.x 与 x.x.x.x/32 视为相同。

    DigitalOcean 返回不带 /32 的地址，而本地/腾讯可能带 /32；统一归一化
    后再做 key 比较与去重，避免同一 IP 被当成两条规则。
    """
    cidr = (cidr or "").strip()
    return cidr[:-3] if cidr.endswith("/32") else cidr


def ensure_cidr(cidr):
    """发送云端前补全 /32（单地址 IPv4 无掩码时）。"""
    cidr = (cidr or "").strip()
    if cidr and "/" not in cidr and ":" not in cidr:
        return f"{cidr}/32"
    return cidr


class CloudFirewallAdapter(AbstractComponent):
    """防火墙白名单适配器契约。

    云服务商模块（cloud_tencent、cloud_digitalocean 等）继承本组件并实现
    ``sync_whitelist``。组件内通过 ``self.collection`` 访问 one.cloud.account
    记录（读取凭证字段），target 参数携带资源 ID 与地域信息。
    """

    _name = "one.cloud.firewall.adapter"
    _collection = "one.cloud.account"

    def sync_whitelist(self, new_ip, target):
        """把 ``new_ip`` 同步到防火墙白名单。

        实现要求：
        - 按 ``Auto whitelist`` 描述前缀识别本工具管理的规则：
          删除 IP 已过期的标记规则，确保新 IP 的全端口 TCP+UDP 规则存在，
          绝不修改非标记规则
        - 幂等：规则集已符合期望时不做任何写操作

        :param new_ip: 新的公网 IPv4
        :param target: one.cloud.firewall.target 记录
        :return: (state, message) 元组，state 为 "success" / "unchanged" /
                 "failed"（失败也可以直接抛异常，由上层捕获记录）
        """
        raise NotImplementedError

    def list_firewalls(self):
        """列出账号下可同步的防火墙资源。

        :return: [{"resource_id": ..., "name": ..., "region": ... or False}, ...]
        """
        raise NotImplementedError

    def list_rules(self, target):
        """列出 target 当前的防火墙规则（只读）。

        :param target: one.cloud.firewall.target 记录
        :return: [{"protocol", "port", "cidr", "action", "description"}, ...]
        """
        raise NotImplementedError

    def push_rules(self, target, local_rules):
        """把本地规则列表推送到云端，按 (协议, 端口, 来源) 三元组 diff。

        规则来源 CIDR 发生变化时（如把旧 IP 换成新 IP），旧来源规则会被
        移除、新来源规则会被添加——即"找到旧 IP 替换成新 IP"。

        :param target: one.cloud.firewall.target 记录
        :param local_rules: [{"protocol", "port", "cidr", "action", "description"}, ...]
        :return: (added, removed, updated) 统计
        """
        raise NotImplementedError
