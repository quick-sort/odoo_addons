from datetime import timedelta

from odoo import api, fields, models


class MailActivity(models.Model):
    _inherit = 'mail.activity'

    reminder_sent = fields.Boolean(
        string="Reminder Sent",
        default=False,
        copy=False,
    )

    @api.model
    def _cron_remind_activities(self):
        today = fields.Date.today()
        projects = self.env['project.project'].search([('activity_reminder_days', '>', 0)])
        for project in projects:
            target_date = today + timedelta(days=project.activity_reminder_days)
            activities = self.env['mail.activity'].search([
                ('active', '=', True),
                ('reminder_sent', '=', False),
                ('date_deadline', '=', target_date),
                '|',
                '&', ('res_model', '=', 'project.project'), ('res_id', '=', project.id),
                '&', ('res_model', '=', 'project.task'), ('res_id', 'in', project.task_ids.ids),
            ])
            for activity in activities:
                activity.action_notify()
                activity.reminder_sent = True
