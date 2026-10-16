from datetime import datetime, time

from pytz import timezone, utc

from odoo import fields, models


class HrHolidaysChinaDay(models.Model):
    _name = 'hr_holidays_china.day'
    _description = 'China Public Holiday Day'
    _order = 'date, id'

    name = fields.Char(required=True)
    date = fields.Date(required=True, index=True)
    kind = fields.Selection(
        [('holiday', 'Holiday'), ('makeup', 'Make-up Work Day')],
        required=True,
    )
    year = fields.Integer(required=True, index=True)
    company_id = fields.Many2one(
        'res.company', required=True, ondelete='cascade', index=True,
        default=lambda self: self.env.company,
    )
    leave_id = fields.Many2one(
        'resource.calendar.leaves', string='Calendar Leave',
        ondelete='set null', readonly=True,
    )

    _date_company_uniq = models.Constraint(
        'unique(company_id, date)',
        'A date can only be recorded once per company.',
    )

    def _leave_datetimes(self, calendar):
        self.ensure_one()
        tz = timezone(calendar.tz or 'Asia/Shanghai')
        date_from = tz.localize(datetime.combine(self.date, time.min)).astimezone(utc).replace(tzinfo=None)
        date_to = tz.localize(datetime.combine(self.date, time.max)).astimezone(utc).replace(tzinfo=None)
        return date_from, date_to

    def _ensure_calendar_leave(self, calendar):
        """Create or update the company-level calendar leave backing this day."""
        for day in self:
            date_from, date_to = day._leave_datetimes(calendar)
            vals = {
                'name': day.name,
                'company_id': day.company_id.id,
                'calendar_id': calendar.id,
                'resource_id': False,
                'time_type': 'leave' if day.kind == 'holiday' else 'other',
                'date_from': date_from,
                'date_to': date_to,
                'china_holiday_day_id': day.id,
            }
            if day.leave_id:
                day.leave_id.write(vals)
            else:
                day.leave_id = self.env['resource.calendar.leaves'].create(vals)
