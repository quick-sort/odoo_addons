# Copyright 2026 Rui
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

from datetime import timedelta

from odoo import api, fields, models

from .one_cloud_firewall_target import STATE_SELECTION


class CloudFirewallSyncLog(models.Model):
    _name = "one.cloud.firewall.sync.log"
    _description = "防火墙同步日志"
    _order = "id desc"
    _rec_name = "create_date"

    target_id = fields.Many2one(
        "one.cloud.firewall.target", required=True, ondelete="cascade", index=True
    )
    provider = fields.Selection(
        related="target_id.provider", store=True
    )
    ip_from = fields.Char(string="原 IP")
    ip_to = fields.Char(string="新 IP")
    state = fields.Selection(STATE_SELECTION, required=True, string="状态")
    message = fields.Text(string="详情")

    @api.model
    def _gc_unchanged_logs(self):
        """无变化日志只保留最近 1 天，成功/失败日志永久保留。"""
        cutoff = fields.Datetime.now().replace(
            hour=0, minute=0, second=0, microsecond=0
        ) - timedelta(days=1)
        stale = self.search(
            [
                ("state", "=", "unchanged"),
                ("create_date", "<", cutoff),
            ]
        )
        if stale:
            stale.unlink()
