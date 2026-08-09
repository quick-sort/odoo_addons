# Copyright 2026 One Storage
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

from odoo import api, models


class ResCompany(models.Model):
    """Ensure every company gets a single One Storage root folder."""

    _inherit = "res.company"

    @api.model_create_multi
    def create(self, vals_list):
        companies = super().create(vals_list)
        for company in companies:
            self.env["one.storage.entry"]._get_or_create_root(company)
        return companies
