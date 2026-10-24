from odoo import api, fields, models


class ProjectMilestone(models.Model):
    _inherit = 'project.milestone'

    last_task_deadline = fields.Date(
        string="Last Task Deadline",
        compute='_compute_last_task_deadline',
        store=True,
    )

    @api.depends('task_ids.date_deadline')
    def _compute_last_task_deadline(self):
        for milestone in self:
            milestone.last_task_deadline = False
        if not self.ids:
            return
        groups = self.env['project.task']._read_group(
            [('milestone_id', 'in', self.ids), ('date_deadline', '!=', False)],
            ['milestone_id'],
            ['date_deadline:max'],
        )
        deadline_per_milestone = {milestone.id: max_deadline for milestone, max_deadline in groups}
        for milestone in self:
            max_deadline = deadline_per_milestone.get(milestone.id)
            if max_deadline:
                milestone.last_task_deadline = max_deadline.date()
