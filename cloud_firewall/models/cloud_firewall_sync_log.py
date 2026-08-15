# Copyright 2026 Rui
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

from odoo import fields, models

from .cloud_firewall_target import STATE_SELECTION


class CloudFirewallSyncLog(models.Model):
    _name = "cloud.firewall.sync.log"
    _description = "防火墙同步日志"
    _order = "id desc"
    _rec_name = "create_date"

    target_id = fields.Many2one(
        "cloud.firewall.target", required=True, ondelete="cascade", index=True
    )
    provider = fields.Selection(
        related="target_id.provider", store=True
    )
    ip_from = fields.Char(string="原 IP")
    ip_to = fields.Char(string="新 IP")
    state = fields.Selection(STATE_SELECTION, required=True, string="状态")
    message = fields.Text(string="详情")
