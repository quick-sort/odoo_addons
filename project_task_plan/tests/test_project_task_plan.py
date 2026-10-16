from odoo import Command, fields
from odoo.exceptions import ValidationError
from odoo.tests import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestProjectTaskPlan(TransactionCase):
    def _dt(self, value):
        return fields.Datetime.from_string(value)

    def _project(self, auto=True):
        return self.env["project.project"].create(
            {
                "name": "Plan Project",
                "allow_task_dependencies": True,
                "allow_auto_schedule": auto,
            }
        )

    def _task(self, project, name, start=None, end=None, deps=(), lead=0.0, no_auto=False):
        vals = {
            "name": name,
            "project_id": project.id,
            "lead_time": lead,
            "no_auto_schedule": no_auto,
        }
        if deps:
            vals["depend_on_ids"] = [Command.set(deps)]
        if start:
            vals["task_start_date"] = start
        if end:
            vals["task_end_date"] = end
        return self.env["project.task"].create(vals)

    # AC-01
    def test_fields_and_defaults(self):
        project = self.env["project.project"].create({"name": "P"})
        self.assertFalse(project.allow_auto_schedule)
        task = self.env["project.task"].create({"name": "T", "project_id": project.id})
        self.assertFalse(task.no_auto_schedule)
        self.assertEqual(task.lead_time, 0.0)

    # AC-02
    def test_lead_time_negative_rejected(self):
        project = self._project()
        with self.assertRaises(ValidationError):
            self._task(project, "T", lead=-1.0)

    # AC-03
    def test_predecessor_push_forward_preserves_duration(self):
        project = self._project()
        a = self._task(project, "A", start=self._dt("2026-01-01 00:00:00"), end=self._dt("2026-01-05 00:00:00"))
        b = self._task(project, "B", start=self._dt("2026-01-05 00:00:00"), end=self._dt("2026-01-10 00:00:00"), deps=[a.id])

        a.write({"task_end_date": self._dt("2026-01-08 00:00:00")})

        self.assertEqual(b.task_start_date, self._dt("2026-01-08 00:00:00"))
        self.assertEqual(b.task_end_date, self._dt("2026-01-13 00:00:00"))

    # AC-04
    def test_predecessor_pull_earlier(self):
        project = self._project()
        a = self._task(project, "A", start=self._dt("2026-01-01 00:00:00"), end=self._dt("2026-01-05 00:00:00"))
        b = self._task(project, "B", start=self._dt("2026-01-05 00:00:00"), end=self._dt("2026-01-10 00:00:00"), deps=[a.id])

        a.write({"task_end_date": self._dt("2026-01-02 00:00:00")})

        self.assertEqual(b.task_start_date, self._dt("2026-01-02 00:00:00"))
        self.assertEqual(b.task_end_date, self._dt("2026-01-07 00:00:00"))

    # AC-05
    def test_multiple_predecessors_take_max(self):
        project = self._project()
        a1 = self._task(project, "A1", start=self._dt("2026-01-01 00:00:00"), end=self._dt("2026-01-10 00:00:00"))
        a2 = self._task(project, "A2", start=self._dt("2026-01-01 00:00:00"), end=self._dt("2026-01-15 00:00:00"))
        b = self._task(project, "B", start=self._dt("2026-01-15 00:00:00"), end=self._dt("2026-01-20 00:00:00"), deps=[a1.id, a2.id])

        a1.write({"task_end_date": self._dt("2026-01-18 00:00:00")})

        self.assertEqual(b.task_start_date, self._dt("2026-01-18 00:00:00"))
        self.assertEqual(b.task_end_date, self._dt("2026-01-23 00:00:00"))

    # AC-06
    def test_lead_time_applied(self):
        project = self._project()
        a = self._task(project, "A", start=self._dt("2026-01-01 00:00:00"), end=self._dt("2026-01-10 00:00:00"))
        b = self._task(project, "B", start=self._dt("2026-01-13 00:00:00"), end=self._dt("2026-01-18 00:00:00"), deps=[a.id], lead=3.0)

        a.write({"task_end_date": self._dt("2026-01-12 00:00:00")})

        self.assertEqual(b.task_start_date, self._dt("2026-01-15 00:00:00"))
        self.assertEqual(b.task_end_date, self._dt("2026-01-20 00:00:00"))

    # AC-07
    def test_predecessor_without_end_date(self):
        project = self._project()
        a = self._task(project, "A", start=self._dt("2026-01-08 00:00:00"))
        b = self._task(project, "B", start=self._dt("2026-01-08 00:00:00"), end=self._dt("2026-01-10 00:00:00"), deps=[a.id])

        a.write({"task_start_date": self._dt("2026-01-12 00:00:00")})

        self.assertEqual(b.task_start_date, self._dt("2026-01-12 00:00:00"))
        self.assertEqual(b.task_end_date, self._dt("2026-01-14 00:00:00"))

    # AC-08
    def test_project_switch_off(self):
        project = self._project(auto=False)
        a = self._task(project, "A", start=self._dt("2026-01-01 00:00:00"), end=self._dt("2026-01-10 00:00:00"))
        b = self._task(project, "B", start=self._dt("2026-01-10 00:00:00"), end=self._dt("2026-01-15 00:00:00"), deps=[a.id])

        a.write({"task_end_date": self._dt("2026-01-12 00:00:00")})

        self.assertEqual(b.task_start_date, self._dt("2026-01-10 00:00:00"))
        self.assertEqual(b.task_end_date, self._dt("2026-01-15 00:00:00"))

    # AC-09
    def test_task_no_auto_schedule(self):
        project = self._project()
        a = self._task(project, "A", start=self._dt("2026-01-01 00:00:00"), end=self._dt("2026-01-10 00:00:00"))
        b = self._task(project, "B", start=self._dt("2026-01-10 00:00:00"), end=self._dt("2026-01-15 00:00:00"), deps=[a.id], no_auto=True)

        a.write({"task_end_date": self._dt("2026-01-12 00:00:00")})

        self.assertEqual(b.task_start_date, self._dt("2026-01-10 00:00:00"))
        self.assertEqual(b.task_end_date, self._dt("2026-01-15 00:00:00"))

    # AC-10
    def test_no_auto_schedule_still_constrains_successor(self):
        project = self._project()
        a = self._task(project, "A", start=self._dt("2026-01-01 00:00:00"), end=self._dt("2026-01-10 00:00:00"))
        b = self._task(project, "B", start=self._dt("2026-01-10 00:00:00"), end=self._dt("2026-01-15 00:00:00"), deps=[a.id], no_auto=True)
        c = self._task(project, "C", start=self._dt("2026-01-15 00:00:00"), end=self._dt("2026-01-20 00:00:00"), deps=[b.id])

        b.write({"task_end_date": self._dt("2026-01-18 00:00:00")})

        self.assertEqual(c.task_start_date, self._dt("2026-01-18 00:00:00"))
        self.assertEqual(c.task_end_date, self._dt("2026-01-23 00:00:00"))

    # AC-11
    def test_task_without_predecessor_not_moved(self):
        project = self._project()
        a = self._task(project, "A", start=self._dt("2026-01-01 00:00:00"), end=self._dt("2026-01-10 00:00:00"))
        b = self._task(project, "B", start=self._dt("2026-01-10 00:00:00"), end=self._dt("2026-01-15 00:00:00"))

        a.write({"task_end_date": self._dt("2026-01-12 00:00:00")})

        self.assertEqual(b.task_start_date, self._dt("2026-01-10 00:00:00"))
        self.assertEqual(b.task_end_date, self._dt("2026-01-15 00:00:00"))

    # AC-12
    def test_transitive_cascade(self):
        project = self._project()
        a = self._task(project, "A", start=self._dt("2026-01-01 00:00:00"), end=self._dt("2026-01-10 00:00:00"))
        b = self._task(project, "B", start=self._dt("2026-01-10 00:00:00"), end=self._dt("2026-01-15 00:00:00"), deps=[a.id])
        c = self._task(project, "C", start=self._dt("2026-01-15 00:00:00"), end=self._dt("2026-01-20 00:00:00"), deps=[b.id])

        a.write({"task_end_date": self._dt("2026-01-12 00:00:00")})

        self.assertEqual(b.task_start_date, self._dt("2026-01-12 00:00:00"))
        self.assertEqual(b.task_end_date, self._dt("2026-01-17 00:00:00"))
        self.assertEqual(c.task_start_date, self._dt("2026-01-17 00:00:00"))
        self.assertEqual(c.task_end_date, self._dt("2026-01-22 00:00:00"))

    # AC-13
    def test_dependency_change_recomputes(self):
        project = self._project()
        a = self._task(project, "A", start=self._dt("2026-01-01 00:00:00"), end=self._dt("2026-01-20 00:00:00"))
        b = self._task(project, "B", start=self._dt("2026-01-10 00:00:00"), end=self._dt("2026-01-15 00:00:00"))

        b.write({"depend_on_ids": [Command.set([a.id])]})

        self.assertEqual(b.task_start_date, self._dt("2026-01-20 00:00:00"))
        self.assertEqual(b.task_end_date, self._dt("2026-01-25 00:00:00"))

    # AC-14
    def test_idempotent(self):
        project = self._project()
        a = self._task(project, "A", start=self._dt("2026-01-01 00:00:00"), end=self._dt("2026-01-10 00:00:00"))
        b = self._task(project, "B", start=self._dt("2026-01-10 00:00:00"), end=self._dt("2026-01-15 00:00:00"), deps=[a.id])

        target = self._dt("2026-01-12 00:00:00")
        a.write({"task_end_date": target})
        a.write({"task_end_date": target})

        self.assertEqual(b.task_start_date, self._dt("2026-01-12 00:00:00"))
        self.assertEqual(b.task_end_date, self._dt("2026-01-17 00:00:00"))

    # AC-15
    def test_cycle_rejected(self):
        project = self._project()
        a = self._task(project, "A")
        b = self._task(project, "B")
        a.write({"depend_on_ids": [Command.set([b.id])]})
        with self.assertRaises(ValidationError):
            b.write({"depend_on_ids": [Command.set([a.id])]})

    # AC-16
    def test_deadline_follows(self):
        project = self._project()
        a = self._task(project, "A", start=self._dt("2026-01-01 00:00:00"), end=self._dt("2026-01-10 00:00:00"))
        b = self._task(project, "B", start=self._dt("2026-01-10 00:00:00"), end=self._dt("2026-01-15 00:00:00"), deps=[a.id])

        a.write({"task_end_date": self._dt("2026-01-12 00:00:00")})

        self.assertEqual(b.date_deadline, b.task_end_date)

    # AC-17 + AC-18
    def test_action_auto_align_and_result(self):
        project = self._project(auto=False)
        a = self._task(project, "A", start=self._dt("2026-01-01 00:00:00"), end=self._dt("2026-01-10 00:00:00"))
        b = self._task(project, "B", start=self._dt("2026-01-05 00:00:00"), end=self._dt("2026-01-08 00:00:00"), deps=[a.id])
        project.write({"allow_auto_schedule": True})

        action = project.action_auto_align()

        self.assertEqual(b.task_start_date, self._dt("2026-01-10 00:00:00"))
        self.assertEqual(b.task_end_date, self._dt("2026-01-13 00:00:00"))

        result = self.env["project.task.plan.result"].browse(action["res_id"])
        self.assertEqual(action["res_model"], "project.task.plan.result")
        self.assertEqual(result.moved_count, 1)
        self.assertEqual(len(result.line_ids), 1)
        line = result.line_ids
        self.assertEqual(line.task_id, b)
        self.assertEqual(line.old_start_date, self._dt("2026-01-05 00:00:00"))
        self.assertEqual(line.old_end_date, self._dt("2026-01-08 00:00:00"))
        self.assertEqual(line.new_start_date, self._dt("2026-01-10 00:00:00"))
        self.assertEqual(line.new_end_date, self._dt("2026-01-13 00:00:00"))

    # AC-19
    def test_ignore_completed_task(self):
        project = self._project()
        a = self._task(project, "A", start=self._dt("2026-01-01 00:00:00"), end=self._dt("2026-01-10 00:00:00"))
        b = self._task(project, "B", start=self._dt("2026-01-10 00:00:00"), end=self._dt("2026-01-15 00:00:00"), deps=[a.id])
        b.write({"state": "1_done"})

        a.write({"task_end_date": self._dt("2026-01-12 00:00:00")})

        self.assertEqual(b.task_start_date, self._dt("2026-01-10 00:00:00"))
        self.assertEqual(b.task_end_date, self._dt("2026-01-15 00:00:00"))
