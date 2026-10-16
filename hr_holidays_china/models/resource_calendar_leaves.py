from odoo import fields, models


class ResourceCalendarLeaves(models.Model):
    _inherit = 'resource.calendar.leaves'

    china_holiday_day_id = fields.Many2one(
        'hr_holidays_china.day', string='China Holiday Day',
        ondelete='cascade', index=True, readonly=True,
    )

    def _prepare_public_holidays_values(self, vals_list):
        # hr_holidays converts public-holiday date_from/date_to from the user's
        # timezone to the calendar's. This module already stores them as UTC, so
        # skip the conversion for the leaves it creates.
        ours = [vals for vals in vals_list if vals.get('china_holiday_day_id')]
        rest = [vals for vals in vals_list if not vals.get('china_holiday_day_id')]
        return ours + super()._prepare_public_holidays_values(rest)
