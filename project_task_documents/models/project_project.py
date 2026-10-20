from odoo import _, fields, models


class ProjectProject(models.Model):
    _inherit = "project.project"

    task_attachment_count = fields.Integer(compute="_compute_task_attachment_count")

    def _compute_task_attachment_count(self):
        for project in self:
            project.task_attachment_count = self.env["ir.attachment"].search_count(
                project._get_task_attachment_domain()
            )

    def _get_task_attachment_domain(self):
        self.ensure_one()
        return [
            ("res_model", "=", "project.task"),
            ("res_id", "in", self.task_ids.ids),
        ]

    def action_view_task_attachments(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Task Documents"),
            "res_model": "ir.attachment",
            "view_mode": "list,form",
            "domain": self._get_task_attachment_domain(),
            "context": {"create": False, "edit": False, "delete": False},
        }
