from odoo import fields, models


class ProjectProject(models.Model):
    _inherit = 'project.project'

    activity_reminder_days = fields.Integer(
        string="Activity Reminder Days",
        default=0,
        help="Send an email reminder this many days before an activity's deadline. "
             "0 disables reminders.",
    )
