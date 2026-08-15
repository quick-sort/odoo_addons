# Copyright 2026 Rui
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

from odoo import fields, models


class CloudFirewallRule(models.Model):
    """持久化的防火墙白名单规则。

    DB 记录是本地的"行 ID"：可在界面上单条增删改，再通过「推送规则」同步到云端
    （DO 按规则内容单条增删，腾讯 Lighthouse 全量 Modify）。
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
