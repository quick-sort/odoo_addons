from odoo import _, fields, models


class ProjectProject(models.Model):
    _inherit = "project.project"

    allow_auto_schedule = fields.Boolean(string="Auto Schedule", default=False)

    def action_auto_align(self):
        """One-shot batch reschedule of every task in the project, then open the result window."""
        self.ensure_one()
        tasks = self.env["project.task"].search([("project_id", "=", self.id)])
        changes = tasks._propagate_schedule(tasks)

        result = self.env["project.task.plan.result"].create({"project_id": self.id})
        line_model = self.env["project.task.plan.result.line"]
        lines = line_model
        for change in changes:
            lines += line_model.create(
                {
                    "result_id": result.id,
                    "task_id": change["task"].id,
                    "old_start_date": change["old_start_date"],
                    "old_end_date": change["old_end_date"],
                    "new_start_date": change["new_start_date"],
                    "new_end_date": change["new_end_date"],
                }
            )
        result.moved_count = len(changes)

        return {
            "type": "ir.actions.act_window",
            "name": _("Auto Align Result"),
            "res_model": "project.task.plan.result",
            "res_id": result.id,
            "view_mode": "form",
            "target": "new",
        }
