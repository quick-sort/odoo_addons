# Copyright 2026 Rui
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

from unittest import mock

from odoo import exceptions
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestSyncConfig(TransactionCase):
    def test_get_singleton_creates_and_reuses(self):
        config_model = self.env["cloud.firewall.sync.config"]
        config_model.search([]).unlink()
        self.assertFalse(config_model.search([]))
        config = config_model._get_singleton()
        self.assertTrue(config.ip_service_url)
        self.assertEqual(config_model._get_singleton(), config)

    def _patch_fetch(self, ip):
        return mock.patch.object(
            type(self.env["cloud.firewall.sync.config"]),
            "_fetch_public_ip",
            return_value=ip,
        )

    def test_action_sync_now_success(self):
        account = self.env["cloud.account"].create(
            {"name": "DO 账号", "provider": "digitalocean", "do_api_token": "t"}
        )
        targets = self.env["cloud.firewall.target"].create(
            [
                {"name": "fw1", "account_id": account.id, "resource_id": "fw-1"},
                {"name": "fw2", "account_id": account.id, "resource_id": "fw-2"},
            ]
        )
        log_model = self.env["cloud.firewall.sync.log"]
        with self._patch_fetch("203.0.113.7"), mock.patch.object(
            type(targets), "_sync_target", return_value=("success", "ok")
        ):
            notification = targets.action_sync_now()
        logs = log_model.search([("target_id", "in", targets.ids)])
        self.assertEqual(len(logs), 2)
        self.assertTrue(all(log.state == "success" for log in logs))
        config = self.env["cloud.firewall.sync.config"]._get_singleton()
        self.assertEqual(config.current_ip, "203.0.113.7")
        self.assertEqual(notification["params"]["type"], "success")

    def test_action_sync_now_isolates_failures(self):
        account = self.env["cloud.account"].create(
            {"name": "DO 账号", "provider": "digitalocean", "do_api_token": "t"}
        )
        targets = self.env["cloud.firewall.target"].create(
            [
                {"name": "ok", "account_id": account.id, "resource_id": "fw-1"},
                {"name": "bad", "account_id": account.id, "resource_id": "fw-2"},
            ]
        )

        with self._patch_fetch("203.0.113.7"), mock.patch.object(
            targets[0], "_sync_target", return_value=("success", "ok")
        ), mock.patch.object(
            targets[1], "_sync_target", side_effect=ValueError("boom")
        ):
            notification = targets.action_sync_now()
        bad_log = self.env["cloud.firewall.sync.log"].search(
            [("target_id.name", "=", "bad")]
        )
        ok_log = self.env["cloud.firewall.sync.log"].search(
            [("target_id.name", "=", "ok")]
        )
        self.assertEqual(bad_log.state, "failed")
        self.assertIn("boom", bad_log.message)
        self.assertEqual(ok_log.state, "success")
        self.assertEqual(notification["params"]["type"], "warning")
        self.assertTrue(notification["params"]["sticky"])

    def test_action_sync_now_empty_recordset_syncs_all(self):
        # 隔离：清空既有目标（事务内回滚，不影响真实数据）
        self.env["cloud.firewall.target"].search([]).unlink()
        account = self.env["cloud.account"].create(
            {"name": "DO 账号", "provider": "digitalocean", "do_api_token": "t"}
        )
        self.env["cloud.firewall.target"].create(
            {"name": "fw1", "account_id": account.id, "resource_id": "fw-1"}
        )
        with self._patch_fetch("203.0.113.7"), mock.patch.object(
            type(self.env["cloud.firewall.target"]), "_sync_target",
            return_value=("unchanged", "same"),
        ):
            self.env["cloud.firewall.target"].action_sync_now()
        self.assertEqual(
            len(self.env["cloud.firewall.sync.log"].search([])), 1
        )

    def test_cron_sync_all_swallows_errors(self):
        with mock.patch.object(
            type(self.env["cloud.firewall.sync.config"]),
            "_fetch_public_ip",
            side_effect=exceptions.UserError("service down"),
        ):
            self.env["cloud.firewall.target"].cron_sync_all()

    def test_cron_sync_all_runs_when_ip_unchanged(self):
        config = self.env["cloud.firewall.sync.config"]._get_singleton()
        config.current_ip = "203.0.113.7"
        with mock.patch.object(
            type(config), "_fetch_public_ip", return_value="203.0.113.7"
        ), mock.patch.object(
            type(self.env["cloud.firewall.target"]), "action_sync_now"
        ) as sync_mock:
            self.env["cloud.firewall.target"].cron_sync_all()
        # IP 未变化也要检查白名单，必须触发同步
        sync_mock.assert_called_once()

    def test_cron_sync_all_runs_when_ip_changed(self):
        config = self.env["cloud.firewall.sync.config"]._get_singleton()
        config.current_ip = "198.51.100.1"
        with mock.patch.object(
            type(config), "_fetch_public_ip", return_value="203.0.113.7"
        ), mock.patch.object(
            type(self.env["cloud.firewall.target"]), "action_sync_now"
        ) as sync_mock:
            self.env["cloud.firewall.target"].cron_sync_all()
        sync_mock.assert_called_once()

    def test_last_sync_computed(self):
        account = self.env["cloud.account"].create(
            {"name": "DO 账号", "provider": "digitalocean", "do_api_token": "t"}
        )
        target = self.env["cloud.firewall.target"].create(
            {"name": "fw1", "account_id": account.id, "resource_id": "fw-1"}
        )
        self.assertFalse(target.last_sync_state)
        self.env["cloud.firewall.sync.log"].create(
            {"target_id": target.id, "ip_to": "1.2.3.4", "state": "success"}
        )
        # computed 非存储字段：清缓存后重新读取
        target.invalidate_recordset(["last_sync_state", "last_sync"])
        self.assertEqual(target.last_sync_state, "success")
        self.assertTrue(target.last_sync)

    def test_action_test_connection(self):
        account = self.env["cloud.account"].create(
            {"name": "DO 账号", "provider": "digitalocean", "do_api_token": "t"}
        )
        fake_adapter = mock.MagicMock()
        with mock.patch.object(
            type(account), "_get_adapter", return_value=fake_adapter
        ):
            notification = account.action_test_connection()
        fake_adapter.validate_config.assert_called_once()
        self.assertEqual(notification["params"]["type"], "success")

    def test_action_test_connection_no_provider(self):
        account = self.env["cloud.account"].new({"name": "x", "provider": False})
        with self.assertRaises(exceptions.UserError):
            account.action_test_connection()

    def test_action_test_connection_unimplemented(self):
        account = self.env["cloud.account"].create(
            {"name": "DO 账号", "provider": "digitalocean", "do_api_token": "t"}
        )
        fake_adapter = mock.MagicMock(spec=[])
        with mock.patch.object(
            type(account), "_get_adapter", return_value=fake_adapter
        ):
            with self.assertRaises(exceptions.UserError):
                account.action_test_connection()

    def test_action_fetch_targets_creates_and_updates(self):
        account = self.env["cloud.account"].create(
            {"name": "DO 账号", "provider": "digitalocean", "do_api_token": "t"}
        )
        self.env["cloud.firewall.target"].create(
            {
                "name": "旧名称",
                "account_id": account.id,
                "resource_id": "fw-existing",
            }
        )
        fake_adapter = mock.MagicMock()
        fake_adapter.list_firewalls.return_value = [
            {"resource_id": "fw-existing", "name": "新名称", "region": False},
            {"resource_id": "fw-new", "name": "新目标", "region": False},
        ]
        with mock.patch.object(
            type(account), "_get_adapter", return_value=fake_adapter
        ):
            notification = account.action_fetch_targets()
        targets = account.target_ids
        self.assertEqual(
            set(targets.mapped("resource_id")), {"fw-existing", "fw-new"}
        )
        existing = targets.filtered(lambda t: t.resource_id == "fw-existing")
        self.assertEqual(existing.name, "新名称")
        new = targets.filtered(lambda t: t.resource_id == "fw-new")
        self.assertTrue(new)
        self.assertIn("新增 1", notification["params"]["message"])
        self.assertIn("更新 1", notification["params"]["message"])

    def test_action_fetch_current_ip(self):
        config = self.env["cloud.firewall.sync.config"]._get_singleton()
        with mock.patch.object(
            type(config), "_fetch_public_ip", return_value="203.0.113.99"
        ):
            notification = config.action_fetch_current_ip()
        self.assertEqual(config.current_ip, "203.0.113.99")
        self.assertIn("203.0.113.99", notification["params"]["message"])

    def test_action_run_cron_triggers_sync(self):
        config = self.env["cloud.firewall.sync.config"]._get_singleton()
        with mock.patch.object(
            type(self.env["cloud.firewall.target"]), "cron_sync_all"
        ) as cron_mock:
            notification = config.action_run_cron()
        cron_mock.assert_called_once()
        self.assertEqual(notification["params"]["type"], "success")

    def test_gc_unchanged_logs_keeps_recent_and_other_states(self):
        from datetime import timedelta

        from odoo.fields import Datetime

        Log = self.env["cloud.firewall.sync.log"]
        account = self.env["cloud.account"].create(
            {"name": "DO 账号", "provider": "digitalocean", "do_api_token": "t"}
        )
        target = self.env["cloud.firewall.target"].create(
            {"name": "fw1", "account_id": account.id, "resource_id": "fw-1"}
        )
        now = Datetime.now()
        old_unchanged = Log.create(
            {"target_id": target.id, "state": "unchanged", "message": "old"}
        )
        recent_unchanged = Log.create(
            {"target_id": target.id, "state": "unchanged", "message": "recent"}
        )
        old_success = Log.create(
            {"target_id": target.id, "state": "success", "message": "keep"}
        )
        old_failed = Log.create(
            {"target_id": target.id, "state": "failed", "message": "keep"}
        )
        # 直接改 create_date 模拟新旧（绕过 readonly）
        cutoff = now.replace(hour=0, minute=0, second=0, microsecond=0) - timedelta(
            days=1
        )
        old_unchanged.create_date = cutoff - timedelta(hours=1)
        old_success.create_date = cutoff - timedelta(days=10)
        old_failed.create_date = cutoff - timedelta(days=10)
        recent_unchanged.create_date = now - timedelta(hours=1)
        Log._gc_unchanged_logs()
        remaining = Log.search([("target_id", "=", target.id)])
        self.assertIn(old_success.id, remaining.ids)
        self.assertIn(old_failed.id, remaining.ids)
        self.assertIn(recent_unchanged.id, remaining.ids)
        self.assertNotIn(old_unchanged.id, remaining.ids)

    def _make_tencent_target(self):
        account = self.env["cloud.account"].create(
            {
                "name": "腾讯账号",
                "provider": "tencent",
                "tencent_secret_id": "id",
                "tencent_secret_key": "key",
                "region_ids": "ap-shanghai",
            }
        )
        return self.env["cloud.firewall.target"].create(
            {"name": "tx", "account_id": account.id, "resource_id": "lhins-1",
             "region": "ap-shanghai"}
        )

    def test_action_sync_rules_imports_updates_removes(self):
        target = self._make_tencent_target()
        Rule = self.env["cloud.firewall.rule"]
        Rule.create(
            {"target_id": target.id, "protocol": "TCP", "port": "ALL",
             "cidr": "1.1.1.1/32", "description": "gone", "remote": True}
        )
        fake_adapter = mock.MagicMock()
        fake_adapter.list_rules.return_value = [
            {"protocol": "TCP", "port": "ALL", "cidr": "2.2.2.2/32",
             "action": "ACCEPT", "description": "hello"},
            {"protocol": "UDP", "port": "ALL", "cidr": "2.2.2.2/32",
             "action": "ACCEPT", "description": "udp"},
        ]
        with mock.patch.object(
            type(target), "_get_adapter", return_value=fake_adapter
        ):
            target.action_sync_rules()
        rules = target.rules_ids
        self.assertEqual(len(rules), 2)
        self.assertTrue(rules.filtered(lambda r: r.cidr == "2.2.2.2" and r.protocol == "TCP"))
        self.assertTrue(rules.filtered(lambda r: r.cidr == "2.2.2.2" and r.protocol == "UDP"))
        self.assertTrue(all(r.remote for r in rules))

    def test_action_sync_rules_dedupes_local_duplicates(self):
        target = self._make_tencent_target()
        Rule = self.env["cloud.firewall.rule"]
        Rule.create(
            [
                {"target_id": target.id, "protocol": "TCP", "port": "ALL",
                 "cidr": "1.2.3.4/32", "remote": True},
                {"target_id": target.id, "protocol": "TCP", "port": "ALL",
                 "cidr": "1.2.3.4", "remote": True},
            ]
        )
        fake_adapter = mock.MagicMock()
        fake_adapter.list_rules.return_value = [
            {"protocol": "TCP", "port": "ALL", "cidr": "1.2.3.4",
             "action": "ACCEPT", "description": ""},
        ]
        with mock.patch.object(
            type(target), "_get_adapter", return_value=fake_adapter
        ):
            target.action_sync_rules()
        tcp = target.rules_ids.filtered(lambda r: r.protocol == "TCP")
        self.assertEqual(len(tcp), 1)
        self.assertEqual(tcp.cidr, "1.2.3.4")

    def test_action_sync_rules_keeps_local_only(self):
        target = self._make_tencent_target()
        Rule = self.env["cloud.firewall.rule"]
        Rule.create(
            {"target_id": target.id, "protocol": "TCP", "port": "ALL",
             "cidr": "9.9.9.9/32", "remote": False}
        )
        fake_adapter = mock.MagicMock()
        fake_adapter.list_rules.return_value = []
        with mock.patch.object(
            type(target), "_get_adapter", return_value=fake_adapter
        ):
            target.action_sync_rules()
        # 本地未推送的规则保留，不因云端缺失被删
        self.assertEqual(len(target.rules_ids), 1)

    def test_rule_delete_syncs_cloud(self):
        target = self._make_tencent_target()
        Rule = self.env["cloud.firewall.rule"]
        Rule.create(
            {"target_id": target.id, "protocol": "TCP", "port": "ALL",
             "cidr": "203.0.113.7/32", "remote": True}
        )
        gone = Rule.create(
            {"target_id": target.id, "protocol": "UDP", "port": "ALL",
             "cidr": "203.0.113.7/32", "remote": True}
        )
        fake_adapter = mock.MagicMock()
        fake_adapter.push_rules.return_value = (0, 1, 0)
        with mock.patch.object(
            type(target), "_get_adapter", return_value=fake_adapter
        ):
            gone.unlink()
        args = fake_adapter.push_rules.call_args[0]
        self.assertEqual(args[0], target)
        # 只把剩余规则推给云端，被删的 UDP 规则不在其中
        self.assertEqual(len(args[1]), 1)
        self.assertEqual(args[1][0]["protocol"], "TCP")
        self.assertEqual(args[1][0]["cidr"], "203.0.113.7/32")

    def test_rule_delete_last_does_not_clear_cloud(self):
        target = self._make_tencent_target()
        only = self.env["cloud.firewall.rule"].create(
            {"target_id": target.id, "protocol": "TCP", "port": "ALL",
             "cidr": "203.0.113.7/32", "remote": True}
        )
        fake_adapter = mock.MagicMock()
        with mock.patch.object(
            type(target), "_get_adapter", return_value=fake_adapter
        ):
            only.unlink()
        # 本地删光时不自动清空云端，避免误删未同步的手工规则
        fake_adapter.push_rules.assert_not_called()

    def test_rule_delete_skip_ctx_no_push(self):
        target = self._make_tencent_target()
        Rule = self.env["cloud.firewall.rule"]
        Rule.create(
            {"target_id": target.id, "protocol": "TCP", "port": "ALL",
             "cidr": "203.0.113.7/32", "remote": True}
        )
        gone = Rule.create(
            {"target_id": target.id, "protocol": "UDP", "port": "ALL",
             "cidr": "203.0.113.7/32", "remote": True}
        )
        fake_adapter = mock.MagicMock()
        with mock.patch.object(
            type(target), "_get_adapter", return_value=fake_adapter
        ):
            gone.with_context(_cloud_skip_push=True).unlink()
        # 内部去重等操作携带 skip context，不触发联动推送
        fake_adapter.push_rules.assert_not_called()

    def test_action_clear_rules_clears_local_and_cloud(self):
        target = self._make_tencent_target()
        Rule = self.env["cloud.firewall.rule"]
        Rule.create(
            [
                {"target_id": target.id, "protocol": "TCP", "port": "ALL",
                 "cidr": "203.0.113.7/32", "remote": True},
                {"target_id": target.id, "protocol": "UDP", "port": "ALL",
                 "cidr": "203.0.113.7/32", "remote": True},
            ]
        )
        fake_adapter = mock.MagicMock()
        fake_adapter.push_rules.return_value = (0, 2, 0)
        with mock.patch.object(
            type(target), "_get_adapter", return_value=fake_adapter
        ):
            notification = target.action_clear_rules()
        # 推空列表给云端清空
        self.assertEqual(fake_adapter.push_rules.call_args[0][1], [])
        # 本地规则清空
        self.assertFalse(target.rules_ids)
        self.assertEqual(notification["params"]["type"], "success")
        self.assertIn("2 条", notification["params"]["message"])

    def test_action_clear_rules_empty_raises(self):
        target = self._make_tencent_target()
        with self.assertRaises(exceptions.UserError):
            target.action_clear_rules()

    def test_action_clear_rules_push_failure_keeps_local(self):
        target = self._make_tencent_target()
        self.env["cloud.firewall.rule"].create(
            {"target_id": target.id, "protocol": "TCP", "port": "ALL",
             "cidr": "203.0.113.7/32", "remote": True}
        )
        fake_adapter = mock.MagicMock()
        fake_adapter.push_rules.side_effect = exceptions.UserError("api down")
        with mock.patch.object(
            type(target), "_get_adapter", return_value=fake_adapter
        ):
            with self.assertRaises(exceptions.UserError):
                target.action_clear_rules()
        # 云端失败时本地规则保留，可重试
        self.assertEqual(len(target.rules_ids), 1)

    def test_action_push_rules_replaces_old_ip(self):
        target = self._make_tencent_target()
        # 云端旧 IP 规则，本地已改成新 IP —— 推送应删旧加新
        fake_adapter = mock.MagicMock()
        fake_adapter.push_rules.return_value = (1, 1, 0)
        rules = self.env["cloud.firewall.rule"]
        rules.create(
            {"target_id": target.id, "protocol": "TCP", "port": "ALL",
             "cidr": "203.0.113.7/32", "remote": False}
        )
        with mock.patch.object(
            type(target), "_get_adapter", return_value=fake_adapter
        ):
            notification = target.action_push_rules()
        args = fake_adapter.push_rules.call_args[0]
        self.assertEqual(args[0], target)
        self.assertEqual(args[1][0]["cidr"], "203.0.113.7/32")
        self.assertTrue(all(r.remote for r in target.rules_ids))
        self.assertIn("新增 1", notification["params"]["message"])

    def test_action_push_rules_empty_raises(self):
        target = self._make_tencent_target()
        with self.assertRaises(exceptions.UserError):
            target.action_push_rules()

    def test_sync_target_adds_when_ip_missing(self):
        target = self._make_tencent_target()
        self.env["cloud.firewall.rule"].create(
            {"target_id": target.id, "protocol": "TCP", "port": "ALL",
             "cidr": "198.51.100.1/32", "remote": True}
        )
        fake_adapter = mock.MagicMock()
        fake_adapter.push_rules.return_value = (2, 1, 0)
        with mock.patch.object(
            type(target), "_get_adapter", return_value=fake_adapter
        ):
            state, message = target._sync_target("203.0.113.7")
        self.assertEqual(state, "success")
        self.assertEqual(target._covered_protocols("203.0.113.7"), {"TCP", "UDP"})
        pushed = fake_adapter.push_rules.call_args[0][1]
        self.assertTrue(any(r["cidr"] == "203.0.113.7" for r in pushed))
        self.assertTrue(all(r.remote for r in target.rules_ids))

    def test_sync_target_backfills_missing_udp(self):
        target = self._make_tencent_target()
        # 数据库里只有 TCP 没有 UDP：cron 应补齐 UDP 而不是跳过
        self.env["cloud.firewall.rule"].create(
            {"target_id": target.id, "protocol": "TCP", "port": "ALL",
             "cidr": "203.0.113.7/32", "remote": True}
        )
        fake_adapter = mock.MagicMock()
        fake_adapter.push_rules.return_value = (1, 0, 0)
        with mock.patch.object(
            type(target), "_get_adapter", return_value=fake_adapter
        ):
            state, message = target._sync_target("203.0.113.7")
        self.assertEqual(state, "success")
        self.assertEqual(target._covered_protocols("203.0.113.7"), {"TCP", "UDP"})
        # 推送的是全量（含已有 TCP + 新 UDP）
        pushed = fake_adapter.push_rules.call_args[0][1]
        self.assertEqual(len(pushed), 2)

    def test_sync_target_skips_when_ip_present(self):
        target = self._make_tencent_target()
        self.env["cloud.firewall.rule"].create(
            [
                {"target_id": target.id, "protocol": "TCP", "port": "ALL",
                 "cidr": "203.0.113.7/32", "remote": True},
                {"target_id": target.id, "protocol": "UDP", "port": "ALL",
                 "cidr": "203.0.113.7/32", "remote": True},
            ]
        )
        fake_adapter = mock.MagicMock()
        with mock.patch.object(
            type(target), "_get_adapter", return_value=fake_adapter
        ):
            state, message = target._sync_target("203.0.113.7")
        self.assertEqual(state, "unchanged")
        fake_adapter.push_rules.assert_not_called()

    def test_sync_target_syncs_rules_first_when_empty(self):
        target = self._make_tencent_target()
        fake_adapter = mock.MagicMock()
        fake_adapter.list_rules.return_value = [
            {"protocol": "TCP", "port": "ALL", "cidr": "198.51.100.1/32",
             "action": "ACCEPT", "description": "Auto whitelist 198.51.100.1 (all ports)"},
            {"protocol": "UDP", "port": "ALL", "cidr": "198.51.100.1/32",
             "action": "ACCEPT", "description": "Auto whitelist 198.51.100.1 (all ports)"},
        ]
        fake_adapter.push_rules.return_value = (2, 2, 0)
        with mock.patch.object(
            type(target), "_get_adapter", return_value=fake_adapter
        ):
            state, message = target._sync_target("203.0.113.7")
        self.assertEqual(state, "success")
        self.assertEqual(target._covered_protocols("203.0.113.7"), {"TCP", "UDP"})
        self.assertEqual(fake_adapter.list_rules.call_count, 1)

    def test_sync_target_normalizes_legacy_lowercase_protocol(self):
        target = self._make_tencent_target()
        # 旧数据小写协议：归一化后 TCP 齐全只补 UDP，且库内大写化
        self.env["cloud.firewall.rule"].create(
            {"target_id": target.id, "protocol": "tcp", "port": "ALL",
             "cidr": "203.0.113.7/32", "remote": True}
        )
        fake_adapter = mock.MagicMock()
        fake_adapter.push_rules.return_value = (1, 0, 0)
        with mock.patch.object(
            type(target), "_get_adapter", return_value=fake_adapter
        ):
            target._sync_target("203.0.113.7")
        self.assertEqual(target._covered_protocols("203.0.113.7"), {"TCP", "UDP"})
        pushed = fake_adapter.push_rules.call_args[0][1]
        self.assertEqual(len(pushed), 2)

    def test_action_sync_rules_normalizes_legacy_formats(self):
        target = self._make_tencent_target()
        Rule = self.env["cloud.firewall.rule"]
        # 旧数据：小写协议 + 小写 action + DO 的 "0" 端口
        Rule.create(
            {"target_id": target.id, "protocol": "tcp", "port": "ALL",
             "cidr": "203.0.113.7/32", "action": "allow", "remote": True}
        )
        fake_adapter = mock.MagicMock()
        fake_adapter.list_rules.return_value = [
            {"protocol": "tcp", "port": "ALL", "cidr": "203.0.113.7",
             "action": "allow", "description": ""},
        ]
        with mock.patch.object(
            type(target), "_get_adapter", return_value=fake_adapter
        ):
            target.action_sync_rules()
        rules = target.rules_ids
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules.protocol, "tcp")  # 远端小写原样导入（provider 域约定）
        self.assertEqual(rules.action, "ALLOW")


@tagged("post_install", "-at_install")
class TestFetchPublicIp(TransactionCase):
    def _config(self):
        config = self.env["cloud.firewall.sync.config"]._get_singleton()
        config.ip_service_url = "http://ipaddress.ai/json"
        return config

    def test_fetch_ip_forces_ipv4_and_keeps_host(self):
        import requests

        config = self._config()
        fake_resp = mock.MagicMock()
        fake_resp.ok = True
        fake_resp.json.return_value = {"ip": "203.0.113.7"}
        with mock.patch.object(
            socket_module(), "getaddrinfo",
            return_value=[(2, 1, 6, "", ("93.184.216.34", 80))],
        ), mock.patch.object(
            requests, "get", return_value=fake_resp
        ) as get_mock:
            ip = config._fetch_public_ip()
        self.assertEqual(ip, "203.0.113.7")
        called_url = get_mock.call_args[0][0]
        self.assertIn("93.184.216.34", called_url)
        self.assertNotIn("ipaddress.ai", called_url)
        self.assertEqual(get_mock.call_args[1]["headers"], {"Host": "ipaddress.ai"})

    def test_fetch_ip_rejects_ipv6(self):
        import requests

        config = self._config()
        fake_resp = mock.MagicMock()
        fake_resp.ok = True
        fake_resp.json.return_value = {"ip": "2001:db8::1"}
        with mock.patch.object(
            socket_module(), "getaddrinfo",
            return_value=[(2, 1, 6, "", ("93.184.216.34", 80))],
        ), mock.patch.object(requests, "get", return_value=fake_resp):
            with self.assertRaises(exceptions.UserError):
                config._fetch_public_ip()

    def test_fetch_ip_http_error(self):
        import requests

        config = self._config()
        fake_resp = mock.MagicMock()
        fake_resp.ok = False
        fake_resp.status_code = 503
        fake_resp.text = "unavailable"
        with mock.patch.object(
            socket_module(), "getaddrinfo",
            return_value=[(2, 1, 6, "", ("93.184.216.34", 80))],
        ), mock.patch.object(requests, "get", return_value=fake_resp):
            with self.assertRaises(exceptions.UserError):
                config._fetch_public_ip()


def socket_module():
    import socket

    return socket
