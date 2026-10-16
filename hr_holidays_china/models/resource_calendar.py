from collections import defaultdict
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

    def _leave_intervals_batch(self, start_dt, end_dt, resources=None, domain=None, tz=None):
        """Return the leave intervals in the given datetime range.

        Mirrors ``resource``'s implementation, but localizes the naive-UTC
        ``date_from``/``date_to`` as UTC before converting them to the
        calendar timezone. The upstream code calls ``astimezone(tz)`` directly
        on naive datetimes, which Python interprets as *system-local* time —
        only correct when the server itself runs in UTC.
        """
        assert start_dt.tzinfo and end_dt.tzinfo

        if domain is None:
            domain = [('time_type', '=', 'leave')]

        resources_list = list(resources) if resources else []

        if self:
            resources_list.append(self.env['resource.resource'])
            domain = domain + [('calendar_id', 'in', [False] + self.ids)]

        domain = domain + [
            ('resource_id', 'in', [False] + [r.id for r in resources_list]),
            ('date_from', '<=', end_dt.astimezone(utc).replace(tzinfo=None)),
            ('date_to', '>=', start_dt.astimezone(utc).replace(tzinfo=None)),
        ]

        result = defaultdict(list)
        tz_dates = {}
        all_leaves = self.env['resource.calendar.leaves'].search(domain)
        for leave in all_leaves:
            leave_resource = leave.resource_id
            leave_company = leave.company_id
            leave_date_from = leave.date_from
            leave_date_to = leave.date_to
            for resource in resources_list:
                if leave_resource.id not in [False, resource.id] or (not leave_resource and resource and resource.company_id != leave_company):
                    continue
                tz = tz if tz else timezone((resource or self).tz)
                if (tz, start_dt) in tz_dates:
                    start = tz_dates[tz, start_dt]
                else:
                    start = start_dt.astimezone(tz)
                    tz_dates[tz, start_dt] = start
                if (tz, end_dt) in tz_dates:
                    end = tz_dates[tz, end_dt]
                else:
                    end = end_dt.astimezone(tz)
                    tz_dates[tz, end_dt] = end
                dt0 = utc.localize(leave_date_from).astimezone(tz)
                dt1 = utc.localize(leave_date_to).astimezone(tz)
                if leave_resource and leave_resource._is_flexible():
                    dt0, dt1 = self._handle_flexible_leave_interval(dt0, dt1, leave)
                result[resource.id].append((max(start, dt0), min(end, dt1), leave))

        return {r.id: Intervals(result[r.id]) for r in resources_list}
