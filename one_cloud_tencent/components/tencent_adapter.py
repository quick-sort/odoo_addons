# Copyright 2026 Rui
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

import re

from odoo import _
from odoo.addons.component.core import Component
from odoo.exceptions import UserError

from odoo.addons.one_cloud_firewall.components.base_adapter import ensure_cidr, norm_cidr

MARKER = "Auto whitelist"

_IP_IN_DESC = re.compile(rf"{MARKER} (\d+\.\d+\.\d+\.\d+)")


def collect_rules(client, instance_id):
    """分页拉取全部防火墙规则。

    ModifyFirewallRules 是全量替换，只读第一页会静默丢失其余规则。

    :return: (rules, firewall_version) rules 为 dict 列表
    """
    rules = []
    version = 0
    offset = 0
    while True:
        req = client.build_describe_request(instance_id, offset)
        resp = client.DescribeFirewallRules(req)
        page = resp.FirewallRuleSet or []
        rules.extend(
            {
                "protocol": getattr(r, "Protocol", "TCP"),
                "port": getattr(r, "Port", "ALL"),
                "cidr": norm_cidr(getattr(r, "CidrBlock", "")),
                "action": getattr(r, "Action", "ACCEPT"),
                "description": getattr(r, "FirewallRuleDescription", ""),
            }
            for r in page
        )
        version = getattr(resp, "FirewallVersion", version)
        offset += len(page)
        total = getattr(resp, "TotalCount", 0)
        if not page or offset >= total:
            break
    return rules, version


def compute_rules(current_rules, new_ip):
    """计算期望的 Lighthouse 防火墙规则集。

    按 ``Auto whitelist`` 描述前缀识别本工具管理的规则：
    - 删除描述中 IP 已过期（非新 IP）的标记规则
    - 确保新 IP 的全端口 TCP+UDP 规则存在（按协议分别补齐）
    - 保留所有非标记规则

    :return: (desired_rules, removed_count, added_count)
    """
    desired = []
    removed = 0
    covered = set()
    for rule in current_rules:
        description = str(rule.get("description") or "")
        if not description.startswith(MARKER):
            desired.append(rule)
            continue
        cidr = rule.get("cidr") or ""
        ip = cidr.split("/")[0]
        described = _IP_IN_DESC.findall(description)
        if ip == new_ip:
            covered.add(rule.get("protocol"))
            desired.append(rule)
        elif ip in described:
            removed += 1
        else:
            # 标记规则但不属于本 IP 管理（如手工改过描述），保留
            desired.append(rule)
    added = 0
    for protocol in ("TCP", "UDP"):
        if protocol not in covered:
            desired.append(
                {
                    "protocol": protocol,
                    "port": "ALL",
                    "cidr": f"{new_ip}/32",
                    "action": "ACCEPT",
                    "description": f"{MARKER} {new_ip} (all ports)",
                }
            )
            added += 1
    return desired, removed, added


def _to_firewall_rule(models, rule):
    new_rule = models.FirewallRule()
    new_rule.Protocol = (rule.get("protocol") or "TCP").upper()
    new_rule.Port = rule.get("port") or "ALL"
    new_rule.CidrBlock = ensure_cidr(rule.get("cidr", ""))
    new_rule.Action = rule.get("action") or "ACCEPT"
    new_rule.FirewallRuleDescription = rule.get("description", "")
    return new_rule


class _PaginatedClient:
    """把请求构造与 collect_rules 解耦，便于测试注入 fake。"""

    def __init__(self, real):
        self._real = real

    def build_describe_request(self, instance_id, offset):
        from tencentcloud.lighthouse.v20200324 import models

        req = models.DescribeFirewallRulesRequest()
        req.InstanceId = instance_id
        req.Offset = offset
        req.Limit = 100
        return req

    def __getattr__(self, name):
        return getattr(self._real, name)


class TencentFirewallAdapter(Component):
    _name = "one.cloud.tencent.firewall.adapter"
    _inherit = "one.cloud.firewall.adapter"
    _usage = "tencent"

    def _build_client(self, region):
        try:
            from tencentcloud.common import credential
            from tencentcloud.common.profile.client_profile import ClientProfile
            from tencentcloud.common.profile.http_profile import HttpProfile
            from tencentcloud.lighthouse.v20200324 import lighthouse_client
        except ImportError as exc:
            raise UserError(
                _(
                    "缺少 Python 依赖 tencentcloud-sdk-python，请先安装：\n"
                    "pip install tencentcloud-sdk-python-lighthouse\n(%s)",
                    exc,
                )
            ) from exc
        http_profile = HttpProfile()
        http_profile.endpoint = "lighthouse.tencentcloudapi.com"
        client_profile = ClientProfile()
        client_profile.httpProfile = http_profile
        cred = credential.Credential(
            self.collection.tencent_secret_id,
            self.collection.tencent_secret_key,
        )
        return lighthouse_client.LighthouseClient(cred, region, client_profile)

    def validate_config(self):
        """DescribeInstances（单个实例）校验密钥与 API 连通性。"""
        from tencentcloud.lighthouse.v20200324 import models

        client = self._build_client(self.collection.tencent_test_region)
        req = models.DescribeInstancesRequest()
        req.Limit = 1
        client.DescribeInstances(req)

    def list_firewalls(self):
        """Lighthouse 无独立防火墙概念，按实例列出（账号内所有地域）。"""
        from tencentcloud.lighthouse.v20200324 import models

        seen = set()
        results = []
        for region in self._list_regions():
            client = self._build_client(region)
            offset = 0
            while True:
                req = models.DescribeInstancesRequest()
                req.Offset = offset
                req.Limit = 100
                resp = client.DescribeInstances(req)
                instances = resp.InstanceSet or []
                for ins in instances:
                    instance_id = ins.InstanceId
                    if instance_id in seen:
                        continue
                    seen.add(instance_id)
                    results.append(
                        {
                            "resource_id": instance_id,
                            "name": getattr(ins, "InstanceName", "") or instance_id,
                            "region": region,
                        }
                    )
                offset += len(instances)
                if not instances or offset >= resp.TotalCount:
                    break
        return results

    def _list_regions(self):
        """地域清单：账号配置的 region_ids 优先，其次已有目标地域 + 测试地域。"""
        regions = []
        for region in str(self.collection.region_ids or "").split(","):
            region = region.strip()
            if region and region not in regions:
                regions.append(region)
        if not regions:
            for target in self.collection.target_ids:
                if target.region and target.region not in regions:
                    regions.append(target.region)
            test_region = self.collection.tencent_test_region
            if test_region and test_region not in regions:
                regions.append(test_region)
        return regions or ["ap-guangzhou"]

    def list_rules(self, target):
        client = self._build_client(target.region)
        rules, _version = collect_rules(_PaginatedClient(client), target.resource_id)
        return rules

    def push_rules(self, target, local_rules):
        """Lighthouse 无单条规则端点，整体 ModifyFirewallRules（带版本号乐观锁）。"""
        from tencentcloud.lighthouse.v20200324 import models

        client = self._build_client(target.region)
        current, version = collect_rules(_PaginatedClient(client), target.resource_id)
        current_keys = {
            (r["protocol"], r["port"], norm_cidr(r["cidr"])) for r in current
        }
        local_keys = {
            (
                (r.get("protocol") or "TCP").upper(),
                r.get("port") or "ALL",
                norm_cidr(r.get("cidr") or ""),
            )
            for r in local_rules
        }
        added = len(local_keys - current_keys)
        removed = len(current_keys - local_keys)
        modify_req = models.ModifyFirewallRulesRequest()
        modify_req.InstanceId = target.resource_id
        modify_req.FirewallVersion = version
        modify_req.FirewallRules = [_to_firewall_rule(models, r) for r in local_rules]
        client.ModifyFirewallRules(modify_req)
        return added, removed, 0

    def sync_whitelist(self, new_ip, target):
        client = self._build_client(target.region)
        current, version = collect_rules(
            _PaginatedClient(client), target.resource_id
        )
        desired, removed, added = compute_rules(current, new_ip)
        if desired == current:
            return "unchanged", "IP 未变化"

        from tencentcloud.lighthouse.v20200324 import models

        modify_req = models.ModifyFirewallRulesRequest()
        modify_req.InstanceId = target.resource_id
        modify_req.FirewallVersion = version
        modify_req.FirewallRules = [
            _to_firewall_rule(models, rule) for rule in desired
        ]
        client.ModifyFirewallRules(modify_req)
        return "success", f"移除 {removed} 条旧规则，新增 {added} 条规则"
