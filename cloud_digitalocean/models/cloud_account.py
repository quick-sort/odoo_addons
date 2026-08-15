# Copyright 2026 Rui
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

from odoo import fields, models


class CloudAccount(models.Model):
    _inherit = "cloud.account"

    provider = fields.Selection(
        selection_add=[("digitalocean", "DigitalOcean")],
        ondelete={"digitalocean": lambda accounts: accounts.unlink()},
    )
    do_api_token = fields.Char(
        string="DigitalOcean API Token",
        groups="cloud.group_cloud_manager",
    )

    _provider_do_token = models.Constraint(
        "CHECK(provider <> 'digitalocean' OR (do_api_token IS NOT NULL AND do_api_token <> ''))",
        "DigitalOcean 账号必须填写 API Token",
    )
