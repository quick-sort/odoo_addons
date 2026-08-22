# Copyright 2026 Rui
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError

from odoo.addons.one_cloud_firewall.components.base_adapter import norm_cidr

_logger = logging.getLogger(__name__)

STATE_SELECTION = [
    ("success", "成功"),
    ("unchanged", "无变化"),
    ("failed", "失败"),
]


class CloudFirewallTarget(models.Model):
    _name = "one.cloud.firewall.target"
    _description = "防火墙目标"
    _order = "name"
    _rec_name = "name"

    name = fields.Char(required=True)
    account_id = fields.Many2one(
        "one.cloud.account", string="云账号", required=True, ondelete="cascade", index=True
    )
    provider = fields.Selection(related="account_id.provider", store=True)
    resource_id = fields.Char(
        required=True,
        string="资源 ID",
        help="DigitalOcean 填防火墙 ID（UUID），腾讯云填 Lighthouse 实例 ID",
    )
    region = fields.Char(
        string="地域",
        help="腾讯云 Lighthouse 实例所在地域，如 ap-shanghai",
    )
    active = fields.Boolean(default=True)
    last_sync_state = fields.Selection(
        STATE_SELECTION, compute="_compute_last_sync", string="最近同步状态"
    )
    last_sync = fields.Datetime(compute="_compute_last_sync", string="最近同步时间")
    sync_log_ids = fields.One2many(
        "one.cloud.firewall.sync.log", "target_id", string="同步日志"
    )
    rules_ids = fields.One2many(
        "one.cloud.firewall.rule", "target_id", string="防火墙规则"
    )

    def _compute_last_sync(self):
        for target in self:
            log = target.sync_log_ids[:1]
            target.last_sync_state = log.state if log else False
            target.last_sync = log.create_date if log else False

    def _get_adapter(self):
        self.ensure_one()
        with self.account_id.work_on("one.cloud.account") as work:
            return work.component(usage=self.account_id.provider)

    def _sync_target(self, new_ip):
        """以本地持久化规则列表为准：TCP/UDP 缺哪个补哪个，缺才推送云端。"""
        self.ensure_one()
        self._dedupe_local_rules()
        if not self.rules_ids:
            # 本地尚无规则：先从云端同步一次，再判断
            self.action_sync_rules()
        covered = self._covered_protocols(new_ip)
        missing = [p for p in ("TCP", "UDP") if p not in covered]
        if not missing:
            return "unchanged", "IP 已在白名单（TCP/UDP 齐全）"
        Rule = self.env["one.cloud.firewall.rule"]
        Rule.create(
            [
                {
                    "target_id": self.id,
                    "protocol": protocol,
                    "port": "ALL",
                    "cidr": new_ip,  # 归一化存储（不带 /32），云端发送时由 adapter 补全
                    "action": "ACCEPT",
                    "description": f"Auto whitelist {new_ip} (all ports)",
                }
                for protocol in missing
            ]
        )
        rules = [
            {
                "protocol": rule.protocol,
                "port": rule.port or "ALL",
                "cidr": rule.cidr,
                "action": rule.action or "ACCEPT",
                "description": rule.description or "",
            }
            for rule in self.rules_ids
        ]
        added, removed, _updated = self._get_adapter().push_rules(self, rules)
        self.rules_ids.write({"remote": True})
        return "success", f"已加入白名单（新增 {added} 条，移除 {removed} 条）"

    def _covered_protocols(self, ip):
        """当前 IP 已有哪些协议的放行规则（按大写协议名）。"""
        covered = set()
        for rule in self.rules_ids:
            if norm_cidr(rule.cidr).split("/")[0] == ip:
                covered.add((rule.protocol or "").upper())
        return covered

    def _dedupe_local_rules(self):
        """按归一化 (协议, 端口, 来源) 清理本地重复规则（如 /32 与不带 /32 并存）。

        去重只是修整本地缓存，不触发云端推送（推送由同步/推送流程统一处理）。
        """
        skip_ctx = {"_cloud_skip_push": True}
        seen = {}
        for rule in self.rules_ids:
            key = ((rule.protocol or "").upper(), rule.port, norm_cidr(rule.cidr))
            existing = seen.get(key)
            if existing is None:
                seen[key] = rule
            elif existing.remote and not rule.remote:
                rule.with_context(**skip_ctx).unlink()
            else:
                rule.with_context(**skip_ctx).unlink()

    def action_sync_rules(self):
        """同步规则：拉取云端规则导入/更新本地持久化列表（云端 → 本地）。"""
        self.ensure_one()
        self._dedupe_local_rules()
        Rule = self.env["one.cloud.firewall.rule"]
        remote_rules = self._get_adapter().list_rules(self)
        existing = {
            ((r.protocol or "").upper(), r.port, norm_cidr(r.cidr)): r
            for r in self.rules_ids
        }
        seen = set()
        created = updated = 0
        for rule in remote_rules:
            cidr = norm_cidr(rule.get("cidr") or "")
            protocol = (rule.get("protocol") or "TCP").upper()
            key = (protocol, rule.get("port") or "ALL", cidr)
            seen.add(key)
            vals = {
                "protocol": protocol,
                "port": rule.get("port") or "ALL",
                "cidr": cidr,
                "action": (rule.get("action") or "ACCEPT").upper(),
                "description": rule.get("description") or "",
                "remote": True,
            }
            if key in existing:
                record = existing[key]
                changed = any(
                    getattr(record, field) != vals[field]
                    for field in ("protocol", "port", "action", "description")
                )
                if changed:
                    record.write(vals)
                    updated += 1
            else:
                Rule.create({"target_id": self.id, **vals})
                created += 1
        removed = 0
        for key, record in existing.items():
            if key not in seen and record.remote:
                record.unlink()
                removed += 1
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("同步规则"),
                "message": _(
                    "新增 %(created)s / 更新 %(updated)s / 移除 %(removed)s",
                    created=created,
                    updated=updated,
                    removed=removed,
                ),
                "type": "success",
                "next": {"type": "ir.actions.client", "tag": "reload"},
            },
        }

    def action_push_rules(self):
        """推送规则：把本地持久化规则列表同步到云端（本地 → 云端）。"""
        self.ensure_one()
        self._dedupe_local_rules()
        if not self.rules_ids:
            raise UserError(
                _("本地规则列表为空，请先点击「同步规则」拉取云端规则，或手动添加规则")
            )
        rules = [
            {
                "protocol": rule.protocol,
                "port": rule.port or "ALL",
                "cidr": rule.cidr,
                "action": rule.action or "ACCEPT",
                "description": rule.description or "",
            }
            for rule in self.rules_ids
        ]
        added, removed, _updated = self._get_adapter().push_rules(self, rules)
        self.rules_ids.write({"remote": True})
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("推送规则"),
                "message": _("新增 %(added)s 条，移除 %(removed)s 条", added=added, removed=removed),
                "type": "success",
                "next": {"type": "ir.actions.client", "tag": "reload"},
            },
        }

    def action_clear_rules(self):
        """清空防火墙规则：本地持久化列表与云端全部清空。"""
        self.ensure_one()
        count = len(self.rules_ids)
        if not count:
            raise UserError(_("本地规则列表已经为空，无需清空"))
        # 先清云端（推送空列表），成功后再清本地：云端失败时本地规则保留可重试，
        # 避免出现"本地已空、云端还有规则"的半状态
        try:
            self._get_adapter().push_rules(self, [])
        except Exception:
            _logger.exception(
                "清空防火墙规则同步云端失败: %s", self.display_name
            )
            raise UserError(_("清空云端防火墙规则失败，本地规则已保留，请稍后重试"))
        self.rules_ids.with_context(_cloud_skip_push=True).unlink()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("清空规则"),
                "message": _("已清空本地与云端防火墙规则（共 %s 条）", count),
                "type": "success",
                "next": {"type": "ir.actions.client", "tag": "reload"},
            },
        }

    def action_sync_now(self):
        """立即同步：列表按钮与 ir.cron 共用入口。"""
        config = self.env["one.cloud.firewall.sync.config"]._get_singleton()
        new_ip = config._fetch_public_ip()
        old_ip = config.current_ip
        counters = {"success": 0, "unchanged": 0, "failed": 0}
        for target in self or self.search([("active", "=", True)]):
            try:
                state, message = target._sync_target(new_ip)
            except Exception as exc:
                _logger.exception(
                    "云防火墙白名单同步失败: %s", target.display_name
                )
                state, message = "failed", f"{type(exc).__name__}: {exc}"
            counters[state] = counters.get(state, 0) + 1
            self.env["one.cloud.firewall.sync.log"].create(
                {
                    "target_id": target.id,
                    "ip_from": old_ip,
                    "ip_to": new_ip,
                    "state": state,
                    "message": message,
                }
            )
        config.write(
            {"current_ip": new_ip, "last_sync": fields.Datetime.now()}
        )
        self.env["one.cloud.firewall.sync.log"]._gc_unchanged_logs()
        failed = counters["failed"]
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("白名单同步"),
                "message": _(
                    "成功 %(success)s / 无变化 %(unchanged)s / 失败 %(failed)s",
                    **counters,
                )
                + (_("，详情见同步日志") if failed else ""),
                "type": "warning" if failed else "success",
                "sticky": bool(failed),
                # 同步会更新 current_ip / last_sync，弹消息后重载列表刷新状态列
                "next": {"type": "ir.actions.client", "tag": "reload"},
            },
        }

    @api.model
    def cron_sync_all(self):
        """定时任务：即使公网 IP 未变化也检查白名单是否包含当前 IP。

        逐目标执行 _sync_target：IP 已在本地白名单则跳过，不在则先拉取最新
        防火墙列表、添加当前 IP 并推送到云端（保证 IP 始终在白名单内）。
        """
        config = self.env["one.cloud.firewall.sync.config"]._get_singleton()
        try:
            new_ip = config._fetch_public_ip()
        except Exception as exc:
            _logger.error("云防火墙白名单定时检查失败: %s", exc)
            return
        if config.current_ip and config.current_ip == new_ip:
            _logger.info("公网 IP 未变化 (%s)，检查白名单是否包含当前 IP", new_ip)
        else:
            _logger.info(
                "公网 IP 已变化: %s -> %s，同步白名单",
                config.current_ip or "(无)",
                new_ip,
            )
        self.action_sync_now()
