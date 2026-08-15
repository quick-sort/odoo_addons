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

    def test_push_rules_all_port_matches_cloud_zero(self):
        from unittest import mock

        adapter = self._adapter()
        # 云端用 "0" 表示所有端口，本地用 "ALL"：同一规则，不能误判为不同触发删除
        adapter.list_rules = mock.MagicMock(
            return_value=[
                {"protocol": "tcp", "port": "0", "cidr": "1.2.3.4",
                 "action": "allow",
                 "description": "Auto whitelist 1.2.3.4 (all ports)"},
            ]
        )
        target = mock.MagicMock(resource_id="fw-1")
        local = [
            {"protocol": "TCP", "port": "ALL", "cidr": "1.2.3.4",
             "action": "ACCEPT",
             "description": "Auto whitelist 1.2.3.4 (all ports)"},
        ]
        added, removed, _updated = adapter.push_rules(target, local)
        self.assertEqual((added, removed), (0, 0))
        adapter._do_api.assert_not_called()

    def test_push_rules_uses_put_when_removing_all(self):
        from unittest import mock

        adapter = self._adapter()
        # 换 IP：云端旧 IP 全量被替换，先 DELETE 会把防火墙删空触发 422，
        # 应改用 PUT 一次性替换最终状态
        adapter.list_rules = mock.MagicMock(
            return_value=[
                {"protocol": "tcp", "port": "ALL", "cidr": "198.51.100.1",
                 "action": "allow", "description": ""},
                {"protocol": "udp", "port": "ALL", "cidr": "198.51.100.1",
                 "action": "allow", "description": ""},
            ]
        )
        adapter._do_api.return_value = {"firewall": {"name": "Home"}}
        target = mock.MagicMock(resource_id="fw-1")
        local = [
            {"protocol": "TCP", "port": "ALL", "cidr": "203.0.113.7",
             "action": "ACCEPT", "description": ""},
            {"protocol": "UDP", "port": "ALL", "cidr": "203.0.113.7",
             "action": "ACCEPT", "description": ""},
        ]
        added, removed, _updated = adapter.push_rules(target, local)
        self.assertEqual((added, removed), (2, 2))
        methods = [args[0][0] for args in adapter._do_api.call_args_list]
        self.assertIn("PUT", methods)
        self.assertNotIn("DELETE", methods)
        put_payload = next(
            args[1]["json_payload"]
            for args in adapter._do_api.call_args_list
            if args[0][0] == "PUT"
        )
        self.assertEqual(len(put_payload["inbound_rules"]), 2)
        self.assertEqual(put_payload["inbound_rules"][0]["ports"], "0")

    def test_push_rules_empty_local_raises(self):
        from unittest import mock

        adapter = self._adapter()
        adapter.list_rules = mock.MagicMock(return_value=[])
        target = mock.MagicMock(resource_id="fw-1")
        from odoo.exceptions import UserError

        with self.assertRaises(UserError):
            adapter.push_rules(target, [])

    def test_to_do_rule_uses_zero_for_all_ports(self):
        adapter = self._adapter()
        rule = adapter._to_do_rule
        self.assertEqual(rule({"port": "ALL"})["ports"], "0")
        self.assertEqual(rule({"port": ""})["ports"], "0")
        self.assertEqual(rule({"port": "443"})["ports"], "443")

    def test_list_rules_normalizes_zero_port_to_all(self):
        from unittest import mock

        adapter = self._adapter()
        adapter._do_api.return_value = {
            "firewall": {
                "inbound_rules": [
                    {"protocol": "tcp", "ports": "0",
                     "sources": {"addresses": ["1.2.3.4/32"]},
                     "action": "allow", "description": ""},
                    {"protocol": "tcp", "ports": "443",
                     "sources": {"addresses": ["5.6.7.8/32"]},
                     "action": "allow", "description": "ssh"},
                ]
            }
        }
        rules = adapter.list_rules(mock.MagicMock(resource_id="fw-1"))
        self.assertEqual(rules[0]["port"], "ALL")
        self.assertEqual(rules[1]["port"], "443")

    def test_list_rules_normalizes_action_and_protocol_case(self):
        from unittest import mock

        adapter = self._adapter()
        adapter._do_api.return_value = {
            "firewall": {
                "inbound_rules": [
                    {"protocol": "tcp", "ports": "0",
                     "sources": {"addresses": ["1.2.3.4/32"]},
                     "action": "allow", "description": ""},
                ]
            }
        }
        rules = adapter.list_rules(mock.MagicMock(resource_id="fw-1"))
        # 本地库统一大写约定：ACCEPT / TCP
        self.assertEqual(rules[0]["action"], "ACCEPT")
        self.assertEqual(rules[0]["protocol"], "TCP")


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
