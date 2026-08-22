# Copyright 2026 Rui
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

from odoo import fields, models


class CloudAccount(models.Model):
    _inherit = "one.cloud.account"

    target_ids = fields.One2many(
        "one.cloud.firewall.target", "account_id", string="防火墙目标"
    )
