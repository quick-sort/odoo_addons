# -*- coding: utf-8 -*-

from odoo import models, fields


class IrActionsActWindowView(models.Model):
    _inherit = 'ir.actions.act_window.view'

    # Add view mode for the new type
    view_mode = fields.Selection(
        selection_add=[('gantt', 'Gantt')],
        ondelete={'gantt': 'cascade'}
    )
