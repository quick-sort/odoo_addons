# -*- coding: utf-8 -*-

from odoo import models, fields


class IrUiView(models.Model):
    _inherit = 'ir.ui.view'

    # Add new view type to selection
    type = fields.Selection(
        selection_add=[('dag', 'DAG')],
        ondelete={'dag': 'cascade'}
    )

    def _get_view_info(self):
        return {'dag': {'icon': 'fa fa-sitemap'}} | super()._get_view_info()
