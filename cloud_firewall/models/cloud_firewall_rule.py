# Copyright 2026 Rui
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

import logging

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)


class CloudFirewallRule(models.Model):
    """持久化的防火墙白名单规则。

    DB 记录是本地的"行 ID"：可在界面上单条增删改，再通过「推送规则」同步到云端
    （DO 按规则内容单条增删，腾讯 Lighthouse 全量 Modify）。删除记录时自动联动
    推送云端同步删除。
    """

    _name = "cloud.firewall.rule"
    _description = "防火墙规则"
    _order = "target_id, id"

    target_id = fields.Many2one(
        "cloud.firewall.target", required=True, ondelete="cascade", index=True
    )
    protocol = fields.Char(required=True, string="协议")
    port = fields.Char(string="端口")
    cidr = fields.Char(required=True, string="来源 (CIDR)")
    action = fields.Char(default="ACCEPT", string="动作")
    description = fields.Char(string="描述")
    remote = fields.Boolean(
        string="已在云端", default=False, readonly=True,
        help="该规则是否已同步到云端（勾选表示云端已存在）",
    )

    _target_proto_port_cidr_uniq = models.Constraint(
        "UNIQUE (target_id, protocol, port, cidr)",
        "同一目标下相同协议/端口/来源的规则只能有一条",
    )

    @api.ondelete(at_uninstall=False)
    def _ondelete_sync_removal(self):
        """删除本地规则后联动推送云端同步删除。

        以目标剩余本地规则全量推送给 adapter（DO 逐条 diff、腾讯全量 Modify），
        被删规则在云端自然消失。本地删光时不自动清空云端，避免误删未同步的
        手工规则；内部去重等操作通过 context 跳过。
        """
        if self.env.context.get("_cloud_skip_push"):
            return
        grouped = {}
        for rule in self:
            grouped.setdefault(rule.target_id, self.env["cloud.firewall.rule"])
            grouped[rule.target_id] |= rule
        for target, removed in grouped.items():
            remaining = target.rules_ids - removed
            if not remaining:
                continue
            rules = [
                {
                    "protocol": rule.protocol,
                    "port": rule.port or "ALL",
                    "cidr": rule.cidr,
                    "action": rule.action or "ACCEPT",
                    "description": rule.description or "",
                }
                for rule in remaining
            ]
            try:
                target._get_adapter().push_rules(target, rules)
            except Exception:
                _logger.exception(
                    "删除规则后同步云端失败: %s", target.display_name
                )
