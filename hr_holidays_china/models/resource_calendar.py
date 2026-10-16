from datetime import datetime

from pytz import timezone, utc

from odoo import models
from odoo.tools.date_utils import float_to_time
from odoo.tools.intervals import Intervals


class ResourceCalendar(models.Model):
    _inherit = 'resource.calendar'

    def _attendance_intervals_batch(self, start_dt, end_dt, resources=None, domain=None, tz=None, lunch=False):
        result = super()._attendance_intervals_batch(start_dt, end_dt, resources, domain, tz, lunch)
        if lunch:
            return result
        makeup = self._makeup_attendance_intervals(start_dt, end_dt, tz)
        if not makeup:
            return result
        for resource_id in result:
            result[resource_id] = result[resource_id] | makeup
        return result

    def _makeup_attendance_intervals(self, start_dt, end_dt, tz=None):
        """Work intervals for make-up work days (调休补班) falling inside the range.

        A make-up day is a weekend that the Chinese official schedule turns into
        a working day. It has no weekly attendance, so it is injected here as
        extra attendance, using the calendar's Monday hours as the template.
        """
        if not self:
            return Intervals()

        utc_start = start_dt.astimezone(utc).replace(tzinfo=None)
        utc_end = end_dt.astimezone(utc).replace(tzinfo=None)
        makeup_leaves = self.env['resource.calendar.leaves'].search([
            ('china_holiday_day_id', '!=', False),
            ('time_type', '=', 'other'),
            ('calendar_id', 'in', self.ids),
            ('date_from', '<=', utc_end),
            ('date_to', '>=', utc_start),
        ])

        intervals = []
        for leave in makeup_leaves:
            calendar = leave.calendar_id
            day = leave.china_holiday_day_id.date
            cal_tz = tz or timezone(calendar.tz or 'Asia/Shanghai')
            template = calendar.attendance_ids.filtered(
                lambda a: a.dayofweek == '0' and a.day_period != 'lunch' and not a.display_type
            )
            if not template:
                template = calendar.attendance_ids.filtered(
                    lambda a: a.day_period != 'lunch' and not a.display_type
                )
            for attendance in template:
                day_from = cal_tz.localize(datetime.combine(day, float_to_time(attendance.hour_from)))
                day_to = cal_tz.localize(datetime.combine(day, float_to_time(attendance.hour_to)))
                intervals.append((day_from, day_to, attendance))
        return Intervals(intervals)
