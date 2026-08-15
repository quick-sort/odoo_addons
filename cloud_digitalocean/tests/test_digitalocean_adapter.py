# Copyright 2026 Rui
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

from odoo.tests import TransactionCase

from odoo.addons.cloud_digitalocean.components.digitalocean_adapter import (
    compute_inbound_rules,
)

from odoo.addons.cloud_firewall.components.base_adapter import norm_cidr

OLD = "198.51.100.1"
NEW = "203.0.113.7"


def rule(ip, protocol="tcp", description=None, addresses=None):
    return {
        "protocol": protocol,
        "ports": "0",
        "sources": {"addresses": addresses or [f"{ip}/32"]},
        "description": description or f"Auto whitelist {ip} (all ports)",
    }


class TestNormCidr(TransactionCase):
    def test_norm_cidr_treats_32_as_same(self):
        self.assertEqual(norm_cidr("1.2.3.4/32"), "1.2.3.4")
        self.assertEqual(norm_cidr("1.2.3.4"), "1.2.3.4")
        self.assertEqual(norm_cidr("10.0.0.0/24"), "10.0.0.0/24")
        self.assertEqual(norm_cidr(""), "")


class TestPushRules(TransactionCase):
    def _adapter(self):
        from unittest import mock

        from odoo.addons.cloud_digitalocean.components.digitalocean_adapter import (
            DigitalOceanFirewallAdapter,
        )

        adapter = object.__new__(DigitalOceanFirewallAdapter)
        adapter._do_api = mock.MagicMock()
        return adapter

    def test_push_rules_cleans_duplicate_cidr(self):
        from unittest import mock

        adapter = self._adapter()
        # 云端同时有 /32 与不带 /32 的同 IP 规则，本地只有一条
        adapter.list_rules = mock.MagicMock(
            return_value=[
                {"protocol": "tcp", "port": "0", "cidr": "1.2.3.4",
                 "action": "allow", "description": ""},
                {"protocol": "tcp", "port": "0", "cidr": "1.2.3.4/32",
                 "action": "allow", "description": ""},
            ]
        )
        target = mock.MagicMock(resource_id="fw-1")
        local = [
            {"protocol": "TCP", "port": "0", "cidr": "1.2.3.4",
             "action": "ACCEPT", "description": ""}
        ]
        added, removed, _updated = adapter.push_rules(target, local)
        self.assertEqual(added, 1)  # 本地一条被重建
        self.assertEqual(removed, 2)  # 云端两条重复被重建清掉
        methods = [args[0][0] for args in adapter._do_api.call_args_list]
        self.assertIn("PUT", methods)
        self.assertNotIn("POST", methods)


class TestComputeInboundRules(TransactionCase):
    def test_removes_expired_marker_and_adds_new(self):
        current = [
            rule(OLD),
            rule(OLD, "udp"),
            rule(NEW),  # 已有新 IP 的 TCP 规则，但缺 UDP
            {
                "protocol": "tcp",
                "ports": "22",
                "sources": {"addresses": ["0.0.0.0/0"]},
                "description": "ssh",
            },
        ]
        desired, removed, added = compute_inbound_rules(current, NEW)
        self.assertEqual(removed, 2)
        self.assertEqual(added, 1)
        ips = [
            a
            for r in desired
            if str(r.get("description", "")).startswith("Auto whitelist")
            for a in r["sources"]["addresses"]
        ]
        self.assertEqual(ips, [f"{NEW}/32", f"{NEW}/32"])
        self.assertTrue(any(r.get("description") == "ssh" for r in desired))

    def test_multi_address_marker_subtracts_only_ours(self):
        current = [
            rule(
                None,
                addresses=[f"{OLD}/32", "10.0.0.1/32"],
                description=f"Auto whitelist {OLD} + manual",
            )
        ]
        desired, removed, added = compute_inbound_rules(current, NEW)
        self.assertEqual(removed, 1)
        marker = next(
            r for r in desired if r["description"].startswith("Auto whitelist")
        )
        self.assertEqual(marker["sources"]["addresses"], ["10.0.0.1/32"])

    def test_unchanged_when_desired_matches(self):
        current = [rule(NEW), rule(NEW, "udp")]
        desired, removed, added = compute_inbound_rules(current, NEW)
        self.assertEqual((removed, added), (0, 0))
        self.assertEqual(desired, current)

    def test_empty_firewall_gets_both_protocols(self):
        desired, removed, added = compute_inbound_rules([], NEW)
        self.assertEqual(added, 2)
        self.assertEqual([r["protocol"] for r in desired], ["tcp", "udp"])
        self.assertTrue(all(r["sources"]["addresses"] == [f"{NEW}/32"] for r in desired))
