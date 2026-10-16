from odoo import fields, models


class ProjectTaskPlanResult(models.TransientModel):
    _name = "project.task.plan.result"
    _description = "Auto Align Result"

    project_id = fields.Many2one("project.project", string="Project", readonly=True)
    moved_count = fields.Integer(string="Moved Tasks", readonly=True)
    line_ids = fields.One2many(
        "project.task.plan.result.line", "result_id", string="Changes"
    )


class ProjectTaskPlanResultLine(models.TransientModel):
    _name = "project.task.plan.result.line"
    _description = "Auto Align Result Line"

    result_id = fields.Many2one(
        "project.task.plan.result", string="Result", ondelete="cascade"
    )
    task_id = fields.Many2one("project.task", string="Task", readonly=True)
    old_start_date = fields.Datetime(string="Old Start", readonly=True)
    old_end_date = fields.Datetime(string="Old End", readonly=True)
    new_start_date = fields.Datetime(string="New Start", readonly=True)
    new_end_date = fields.Datetime(string="New End", readonly=True)
