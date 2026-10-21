from odoo import _, fields, models


class ProjectProject(models.Model):
    _inherit = "project.project"

    task_meeting_count = fields.Integer(compute="_compute_task_meeting_count")

    def _compute_task_meeting_count(self):
        for project in self:
            project.task_meeting_count = self.env["calendar.event"].search_count(
                project._get_task_meeting_domain()
            )

    def _get_task_meeting_domain(self):
        self.ensure_one()
        return [
            ("res_model", "=", "project.task"),
            ("res_id", "in", self.task_ids.ids),
        ]

    def action_view_task_meetings(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Task Meetings"),
            "res_model": "calendar.event",
            "view_mode": "calendar,form",
            "domain": self._get_task_meeting_domain(),
            "context": {"create": False, "edit": False, "delete": False},
        }
