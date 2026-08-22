# Copyright 2026 Rui
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

from odoo.tests import TransactionCase

from odoo.addons.one_cloud_tencent.components.tencent_adapter import (
    collect_rules,
    compute_rules,
)

OLD = "198.51.100.1"
NEW = "203.0.113.7"


def rule(ip, protocol="TCP", description=None):
    return {
        "protocol": protocol,
        "port": "ALL",
        "cidr": f"{ip}/32",
        "action": "ACCEPT",
        "description": description or f"Auto whitelist {ip} (all ports)",
    }


class TestComputeRules(TransactionCase):
    def test_removes_expired_marker_and_adds_new(self):
        current = [
            rule(OLD),
            rule(OLD, "UDP"),
            rule(NEW),  # 已有 TCP，缺 UDP
            {
                "protocol": "TCP",
                "port": "22",
                "cidr": "0.0.0.0/0",
                "action": "ACCEPT",
                "description": "ssh",
            },
        ]
        desired, removed, added = compute_rules(current, NEW)
        self.assertEqual(removed, 2)
        self.assertEqual(added, 1)
        markers = [r for r in desired if r["description"].startswith("Auto whitelist")]
        self.assertEqual([m["cidr"] for m in markers], [f"{NEW}/32", f"{NEW}/32"])
        self.assertTrue(any(r["description"] == "ssh" for r in desired))

    def test_unchanged_when_desired_matches(self):
        current = [rule(NEW), rule(NEW, "UDP")]
        desired, removed, added = compute_rules(current, NEW)
        self.assertEqual((removed, added), (0, 0))
        self.assertEqual(desired, current)

    def test_empty_firewall_gets_both_protocols(self):
        desired, removed, added = compute_rules([], NEW)
        self.assertEqual(added, 2)
        self.assertEqual([r["protocol"] for r in desired], ["TCP", "UDP"])
        self.assertTrue(all(r["cidr"] == f"{NEW}/32" for r in desired))


class _FakeRule:
    def __init__(self, cidr, description=""):
        self.Protocol = "TCP"
        self.Port = "ALL"
        self.CidrBlock = cidr
        self.Action = "ACCEPT"
        self.FirewallRuleDescription = description


class _FakeResp:
    def __init__(self, rules, total, version):
        self.FirewallRuleSet = rules
        self.TotalCount = total
        self.FirewallVersion = version


class _FakeClient:
    """按 Offset/Limit=100 分页返回规则。"""

    def __init__(self, total=150):
        self.total = total
        self.calls = []

    def build_describe_request(self, instance_id, offset):
        return {"instance_id": instance_id, "offset": offset}

    def DescribeFirewallRules(self, req):
        self.calls.append(req)
        offset = req["offset"]
        page = [
            _FakeRule(f"10.0.{offset // 100}.{i}/32", f"rule-{offset}-{i}")
            for i in range(min(100, self.total - offset))
        ]
        return _FakeResp(page, self.total, version=42)


class TestCollectRules(TransactionCase):
    def test_collect_rules_paginates(self):
        client = _FakeClient(total=150)
        rules, version = collect_rules(client, "lhins-1")
        self.assertEqual(len(rules), 150)
        self.assertEqual(version, 42)
        self.assertEqual(len(client.calls), 2)
        self.assertEqual(
            rules[0],
            {
                "protocol": "TCP",
                "port": "ALL",
                "cidr": "10.0.0.0",  # norm_cidr 去掉了 /32
                "action": "ACCEPT",
                "description": "rule-0-0",
            },
        )

    def test_collect_rules_single_page(self):
        client = _FakeClient(total=5)
        rules, version = collect_rules(client, "lhins-1")
        self.assertEqual(len(rules), 5)
        self.assertEqual(len(client.calls), 1)
