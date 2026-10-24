from collections import deque
from datetime import timedelta

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError

_SCHEDULE_FIELDS = {
    "task_start_date",
    "date_deadline",
    "depend_on_ids",
    "lead_time",
    "no_auto_schedule",
}
_SELF_CONSTRAINT_FIELDS = {"depend_on_ids", "lead_time", "no_auto_schedule"}


class ProjectTask(models.Model):
    _inherit = "project.task"

    no_auto_schedule = fields.Boolean(string="No Auto Schedule", default=False)
    lead_time = fields.Float(string="Lead Time (Days)", default=0.0, digits=(16, 2))

    @api.constrains("lead_time")
    def _check_lead_time(self):
        for task in self:
            if task.lead_time < 0:
                raise ValidationError(_("Lead Time cannot be negative."))

    def _is_auto_schedulable(self):
        self.ensure_one()
        return (
            self.project_id.allow_auto_schedule
            and not self.no_auto_schedule
            and not self.is_closed
            and bool(self.depend_on_ids)
            and bool(self.task_start_date or self.date_deadline)
        )

    def _compute_target_dates(self):
        self.ensure_one()
        ends = [
            pred.date_deadline or pred.task_start_date
            for pred in self.depend_on_ids
            if pred.date_deadline or pred.task_start_date
        ]
        if not ends:
            return self.task_start_date, self.date_deadline
        start = max(ends) + timedelta(days=self.lead_time)
        return start, start + timedelta(days=(self.gantt_duration or 0.0))

    def _propagate_schedule(self, roots):
        """Recompute ``roots`` and their transitive successors, topologically.

        Returns a list of change dicts for the tasks that actually moved.
        """
        if self.env.context.get("_auto_schedule_guard"):
            return []
        roots = roots.filtered(lambda t: t.project_id.allow_auto_schedule)
        if not roots:
            return []
        project_ids = set(roots.project_id.ids)

        seen = {}
        queue = list(roots)
        affected = []
        while queue:
            task = queue.pop(0)
            if task.id in seen:
                continue
            seen[task.id] = task
            affected.append(task)
            for succ in task.dependent_ids:
                if succ.id not in seen and succ.project_id.id in project_ids:
                    queue.append(succ)

        affected_ids = set(seen)
        indegree = {task.id: 0 for task in affected}
        adjacency = {task.id: [] for task in affected}
        for task in affected:
            for pred in task.depend_on_ids:
                if pred.id in affected_ids:
                    indegree[task.id] += 1
                    adjacency[pred.id].append(task.id)

        dq = deque(task.id for task in affected if indegree[task.id] == 0)
        order = []
        while dq:
            tid = dq.popleft()
            order.append(seen[tid])
            for sid in adjacency[tid]:
                indegree[sid] -= 1
                if indegree[sid] == 0:
                    dq.append(sid)

        changes = []
        for task in order:
            if not task._is_auto_schedulable():
                continue
            new_start, new_end = task._compute_target_dates()
            if new_start != task.task_start_date or new_end != task.date_deadline:
                old_start, old_end = task.task_start_date, task.date_deadline
                task.with_context(_auto_schedule_guard=True).write(
                    {"task_start_date": new_start, "date_deadline": new_end}
                )
                changes.append(
                    {
                        "task": task,
                        "old_start_date": old_start,
                        "old_end_date": old_end,
                        "new_start_date": new_start,
                        "new_end_date": new_end,
                    }
                )
        return changes

    @api.model_create_multi
    def create(self, vals_list):
        records = super().create(vals_list)
        if not self.env.context.get("_auto_schedule_guard"):
            roots = records.filtered("depend_on_ids")
            if roots:
                records._propagate_schedule(roots)
        return records

    def write(self, vals):
        changed = _SCHEDULE_FIELDS & set(vals)
        self_constraint_changed = bool(changed & _SELF_CONSTRAINT_FIELDS)
        result = super().write(vals)
        if changed and not self.env.context.get("_auto_schedule_guard"):
            roots = self if self_constraint_changed else self.mapped("dependent_ids")
            self._propagate_schedule(roots)
        return result
