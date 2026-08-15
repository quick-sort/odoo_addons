# Copyright 2026 Rui
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

from odoo import models


class CloudFirewallTarget(models.Model):
    _inherit = "cloud.firewall.target"

    _provider_tencent_region = models.Constraint(
        "CHECK(provider <> 'tencent' OR (region IS NOT NULL AND region <> ''))",
        "腾讯云目标必须填写地域",
    )
