# Copyright 2026 Rui
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

import re

from odoo import _
from odoo.addons.component.core import Component
from odoo.exceptions import UserError

from odoo.addons.cloud_firewall.components.base_adapter import ensure_cidr, norm_cidr

MARKER = "Auto whitelist"

_IP_IN_DESC = re.compile(rf"{MARKER} (\d+\.\d+\.\d+\.\d+)")


def _described_ips(description):
    """从标记规则描述中解析出本工具管理的 IP（描述形如 ``Auto whitelist 1.2.3.4 ...``）。"""
    return {m.group(1) for m in _IP_IN_DESC.finditer(description or "")}


def compute_inbound_rules(current_rules, new_ip):
    """计算期望的 DO 入站规则集。

    按 ``Auto whitelist`` 描述前缀识别本工具管理的规则：
    - 移除标记规则中 IP 已过期（描述中提及且非新 IP）的地址；
      还有其他地址则保留该规则
    - 确保新 IP 的全端口 TCP+UDP 规则存在（按协议分别补齐）
    - 保留所有非标记规则

    :return: (desired_rules, removed_count, added_count)
    """
    new_addrs = (f"{new_ip}/32", new_ip)
    desired = []
    removed = 0
    covered = set()
    for rule in current_rules:
        sources = rule.get("sources") or {}
        addresses = sources.get("addresses")
        description = str(rule.get("description") or "")
        if not addresses or not description.startswith(MARKER):
            desired.append(rule)
            continue
        described = _described_ips(description)
        keep = []
        dropped = []
        for addr in addresses:
            ip = addr.split("/")[0]
            if ip in described and ip != new_ip:
                dropped.append(addr)
            else:
                keep.append(addr)
                if addr in new_addrs:
                    covered.add(rule.get("protocol"))
        if not dropped:
            desired.append(rule)
        elif keep:
            new_rule = dict(rule)
            new_rule["sources"] = {**sources, "addresses": keep}
            desired.append(new_rule)
            removed += len(dropped)
        else:
            removed += len(dropped)
    added = 0
    for protocol, suffix in (("tcp", "(all ports)"), ("udp", "(all ports UDP)")):
        if protocol not in covered:
            desired.append(
                {
                    "protocol": protocol,
                    "ports": "0",
                    "sources": {"addresses": [f"{new_ip}/32"]},
                    "description": f"{MARKER} {new_ip} {suffix}",
                }
            )
            added += 1
    return desired, removed, added


class DigitalOceanFirewallAdapter(Component):
    _name = "cloud.digitalocean.firewall.adapter"
    _inherit = "cloud.firewall.adapter"
    _usage = "digitalocean"

    def _do_api(self, method, path, json_payload=None, params=None):
        import requests

        token = self.collection.do_api_token
        resp = requests.request(
            method,
            f"https://api.digitalocean.com/v2{path}",
            headers={"Authorization": f"Bearer {token}"},
            json=json_payload,
            params=params,
            timeout=30,
        )
        if not resp.ok:
            raise UserError(
                _(
                    "DigitalOcean API HTTP %s: %s",
                    resp.status_code,
                    resp.text[:500],
                )
            )
        return resp.json() if resp.content else {}

    def validate_config(self):
        """GET /firewalls 校验 token 与 API 连通性（只读 token 亦可用）。"""
        self._do_api("GET", "/firewalls", params={"per_page": 1})

    def list_firewalls(self):
        data = self._do_api("GET", "/firewalls", params={"per_page": 200})
        return [
            {
                "resource_id": fw["id"],
                "name": fw.get("name") or fw["id"],
                "region": False,
            }
            for fw in data.get("firewalls") or []
        ]

    def list_rules(self, target):
        firewall = self._do_api(
            "GET", f"/firewalls/{target.resource_id}"
        ).get("firewall", {})
        return [
            {
                "protocol": rule.get("protocol"),
                "port": rule.get("ports"),
                "cidr": norm_cidr(
                    ", ".join((rule.get("sources") or {}).get("addresses") or [])
                ),
                "action": rule.get("action") or "allow",
                "description": rule.get("description") or "",
            }
            for rule in firewall.get("inbound_rules") or []
        ]

    @staticmethod
    def _normalize_action(action):
        return "allow" if (action or "allow").lower() in ("allow", "accept") else "drop"

    @staticmethod
    def _to_do_rule(rule):
        return {
            "protocol": (rule.get("protocol") or "TCP").lower(),
            "ports": rule.get("port") or "0",
            "sources": {"addresses": [ensure_cidr(rule.get("cidr") or "")]},
            "action": "allow",
            "description": rule.get("description") or "",
        }

    def push_rules(self, target, local_rules):
        current = self.list_rules(target)

        def key(rule):
            return (
                str(rule.get("protocol") or "").lower(),
                str(rule.get("port") or ""),
                norm_cidr(str(rule.get("cidr") or "")),
            )

        # 云端存在归一化后相同的重复规则（如 /32 与不带 /32 并存）时，
        # 单条 DELETE 无法定位删除其中一条，改为全量 PUT 重建清掉重复
        current_keys = [key(rule) for rule in current]
        if len(current_keys) != len(set(current_keys)):
            firewall = self._do_api(
                "GET", f"/firewalls/{target.resource_id}"
            ).get("firewall", {})
            payload = {
                "name": firewall.get("name", ""),
                "inbound_rules": [self._to_do_rule(rule) for rule in local_rules],
                "outbound_rules": firewall.get("outbound_rules") or [],
                "droplet_ids": firewall.get("droplet_ids") or [],
                "tags": firewall.get("tags") or [],
            }
            self._do_api("PUT", f"/firewalls/{target.resource_id}", payload)
            return len(local_rules), len(current), 0

        local_by_key = {key(rule): rule for rule in local_rules}

        def content_differs(local, remote):
            return (
                self._normalize_action(local.get("action"))
                != self._normalize_action(remote.get("action"))
                or (local.get("description") or "") != (remote.get("description") or "")
            )

        # 逐条比较：云端任何规则（含同归一化 key 的重复）只要不在本地或内容不同
        # 就删除，本地需要而云端缺失/内容不同的重新添加。
        # 本地规则 CIDR 变更（旧 IP → 新 IP）时，旧来源进 to_delete、新来源进
        # to_add，即"找到旧 IP 替换成新 IP"；云端 /32 与不带 /32 的重复也会被清理。
        to_delete = []
        for remote in current:
            local = local_by_key.get(key(remote))
            if local is None or content_differs(local, remote):
                to_delete.append(remote)
        current_keys = {key(rule) for rule in current}
        to_add = []
        for key_, local in local_by_key.items():
            if key_ not in current_keys:
                to_add.append(local)
            elif any(
                content_differs(local, remote)
                for remote in current
                if key(remote) == key_
            ):
                to_add.append(local)

        if to_delete:
            self._do_api(
                "DELETE",
                f"/firewalls/{target.resource_id}/rules",
                json_payload={"inbound_rules": [self._to_do_rule(r) for r in to_delete]},
            )
        if to_add:
            self._do_api(
                "POST",
                f"/firewalls/{target.resource_id}/rules",
                json_payload={"inbound_rules": [self._to_do_rule(r) for r in to_add]},
            )
        return len(to_add), len(to_delete), 0

    def sync_whitelist(self, new_ip, target):
        firewall = self._do_api(
            "GET", f"/firewalls/{target.resource_id}"
        ).get("firewall", {})
        current = firewall.get("inbound_rules") or []
        desired, removed, added = compute_inbound_rules(current, new_ip)
        if desired == current:
            return "unchanged", "IP 未变化"
        payload = {
            "name": firewall.get("name", ""),
            "inbound_rules": desired,
            "outbound_rules": firewall.get("outbound_rules") or [],
            "droplet_ids": firewall.get("droplet_ids") or [],
            "tags": firewall.get("tags") or [],
        }
        self._do_api("PUT", f"/firewalls/{target.resource_id}", payload)
        return "success", f"移除 {removed} 条旧规则，新增 {added} 条规则"
