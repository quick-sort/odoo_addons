# -*- coding: utf-8 -*-

from odoo import models, fields


class IrUiView(models.Model):
    _inherit = 'ir.ui.view'

    # Add new view type to selection
    type = fields.Selection(
        selection_add=[('gantt', 'Gantt')],
        ondelete={'gantt': 'cascade'}
    )

    def _get_view_info(self):
        return {'gantt': {'icon': 'fa fa-tasks'}} | super()._get_view_info()
