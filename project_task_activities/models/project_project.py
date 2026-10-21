from odoo import _, fields, models


class ProjectProject(models.Model):
    _inherit = "project.project"

    task_activity_count = fields.Integer(compute="_compute_task_activity_count")

    def _compute_task_activity_count(self):
        for project in self:
            project.task_activity_count = self.env["mail.activity"].search_count(
                project._get_task_activity_domain()
            )

    def _get_task_activity_domain(self):
        self.ensure_one()
        return [
            ("res_model", "=", "project.task"),
            ("res_id", "in", self.task_ids.ids),
        ]

    def action_view_task_activities(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Task Activities"),
            "res_model": "mail.activity",
            "view_mode": "list,form",
            "domain": self._get_task_activity_domain(),
            "context": {"create": False, "edit": False, "delete": False},
        }
