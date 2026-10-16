from datetime import date, datetime, time
from unittest.mock import patch

from pytz import timezone

from odoo.tests.common import TransactionCase, tagged

PAYLOAD = {
    'year': 2026,
    'papers': ['https://www.gov.cn/notice'],
    'days': [
        {'name': '劳动节', 'date': '2026-05-01', 'isOffDay': True},
        {'name': '劳动节', 'date': '2026-05-09', 'isOffDay': False},
    ],
}


@tagged('post_install', '-at_install')
class TestHrHolidaysChina(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.company = cls.env.company
        cls.calendar = cls.env['resource.calendar'].create({
            'name': 'China Test',
            'tz': 'Asia/Shanghai',
            'attendance_ids': [
                (0, 0, {
                    'name': 'Mon-Fri',
                    'dayofweek': day,
                    'hour_from': 9.0,
                    'hour_to': 18.0,
                    'day_period': 'full_day',
                })
                for day in ('0', '1', '2', '3', '4')
            ],
        })
        cls.company.hr_holidays_china_calendar_id = cls.calendar

    def _sync(self):
        with patch.object(
            type(self.env['res.company']), '_fetch_china_holidays_json',
            return_value=PAYLOAD,
        ):
            self.company._sync_china_holidays(2026)

    def _work_hours(self, day_date):
        tz = timezone('Asia/Shanghai')
        start = tz.localize(datetime.combine(day_date, time.min))
        end = tz.localize(datetime.combine(day_date, time.max))
        return self.calendar.get_work_hours_count(start, end)

    def test_sync_creates_days_and_leaves(self):
        self._sync()
        days = self.env['hr_holidays_china.day'].search([('company_id', '=', self.company.id)])
        self.assertEqual(len(days), 2)

        holiday = days.filtered(lambda d: d.kind == 'holiday')
        makeup = days.filtered(lambda d: d.kind == 'makeup')
        self.assertEqual(holiday.date, date(2026, 5, 1))
        self.assertEqual(makeup.date, date(2026, 5, 9))

        self.assertEqual(holiday.leave_id.time_type, 'leave')
        self.assertEqual(makeup.leave_id.time_type, 'other')
        self.assertFalse(holiday.leave_id.resource_id)
        self.assertEqual(holiday.leave_id.calendar_id, self.calendar)

    def test_sync_is_idempotent(self):
        self._sync()
        self._sync()
        days = self.env['hr_holidays_china.day'].search([('company_id', '=', self.company.id)])
        leaves = self.env['resource.calendar.leaves'].search([('china_holiday_day_id', '!=', False)])
        self.assertEqual(len(days), 2)
        self.assertEqual(len(leaves), 2)

    def test_holiday_is_not_working(self):
        self._sync()
        self.assertEqual(self._work_hours(date(2026, 5, 1)), 0.0)

    def test_makeup_day_is_working(self):
        self._sync()
        self.assertEqual(self._work_hours(date(2026, 5, 9)), 9.0)

    def test_normal_weekday_still_working(self):
        self._sync()
        self.assertEqual(self._work_hours(date(2026, 5, 4)), 9.0)
