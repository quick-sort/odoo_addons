import logging
from datetime import date

import requests

from odoo import _, fields, models

_logger = logging.getLogger(__name__)

DEFAULT_URL_TEMPLATE = 'https://raw.githubusercontent.com/NateScarlet/holiday-cn/master/{year}.json'
MAX_BYTES = 5 * 1024 * 1024


class ResCompany(models.Model):
    _inherit = 'res.company'

    hr_holidays_china_calendar_id = fields.Many2one(
        'resource.calendar', string='China Holidays Calendar',
        help='Working calendar to write China public holidays into. '
             'Leave empty to use the company default calendar.',
    )
    hr_holidays_china_auto_update = fields.Boolean(
        string='Auto-update China Holidays', default=True,
    )

    def _china_holidays_calendar(self):
        self.ensure_one()
        return self.hr_holidays_china_calendar_id or self.resource_calendar_id

    def _china_holidays_url(self, year):
        template = self.env['ir.config_parameter'].sudo().get_param(
            'hr_holidays_china.url_template', DEFAULT_URL_TEMPLATE)
        return template.format(year=year)

    def _fetch_china_holidays_json(self, year):
        url = self._china_holidays_url(year)
        if not url.startswith('https://'):
            raise ValueError(_("China holidays data source must use https: %s", url))
        response = requests.get(url, timeout=30)
        response.raise_for_status()
        if len(response.content) > MAX_BYTES:
            raise ValueError(_("China holidays data source is unexpectedly large"))
        return response.json()

    def _sync_china_holidays(self, year):
        self.ensure_one()
        data = self._fetch_china_holidays_json(year)
        calendar = self._china_holidays_calendar()
        day_model = self.env['hr_holidays_china.day']
        for entry in data.get('days', []):
            day_date = date.fromisoformat(entry['date'])
            kind = 'holiday' if entry['isOffDay'] else 'makeup'
            day = day_model.search(
                [('company_id', '=', self.id), ('date', '=', day_date)], limit=1)
            vals = {'name': entry['name'], 'kind': kind, 'year': year}
            if day:
                day.write(vals)
            else:
                vals.update({'company_id': self.id, 'date': day_date})
                day = day_model.create(vals)
            day._ensure_calendar_leave(calendar)

    def action_sync_china_holidays(self):
        today = date.today()
        for company in self:
            for year in {today.year, today.year + 1}:
                company._sync_china_holidays(year)
        return True

    def _cron_sync_china_holidays(self):
        companies = self.search([('hr_holidays_china_auto_update', '=', True)])
        companies.action_sync_china_holidays()
