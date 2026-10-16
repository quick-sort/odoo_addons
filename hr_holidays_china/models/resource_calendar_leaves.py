from odoo import fields, models


class ResourceCalendarLeaves(models.Model):
    _inherit = 'resource.calendar.leaves'

    china_holiday_day_id = fields.Many2one(
        'hr_holidays_china.day', string='China Holiday Day',
        ondelete='cascade', index=True, readonly=True,
    )
