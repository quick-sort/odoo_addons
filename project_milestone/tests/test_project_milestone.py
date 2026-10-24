from datetime import date

from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestProjectMilestoneLastTaskDeadline(TransactionCase):

    def _create_project(self):
        return self.env['project.project'].create({
            'name': 'Test Project',
            'allow_milestones': True,
        })

    def _create_milestone(self, project):
        return self.env['project.milestone'].create({
            'name': 'Test Milestone',
            'project_id': project.id,
        })

    def _create_task(self, project, milestone, deadline=False):
        values = {
            'name': 'Test Task',
            'project_id': project.id,
            'milestone_id': milestone.id,
        }
        if deadline:
            values['date_deadline'] = deadline
        return self.env['project.task'].create(values)

    def test_last_task_deadline_is_latest_deadline(self):
        project = self._create_project()
        milestone = self._create_milestone(project)
        self._create_task(project, milestone, '2026-01-10')
        self._create_task(project, milestone, '2026-02-20')
        self.assertEqual(milestone.last_task_deadline, date(2026, 2, 20))

    def test_last_task_deadline_ignores_tasks_without_deadline(self):
        project = self._create_project()
        milestone = self._create_milestone(project)
        self._create_task(project, milestone)
        self._create_task(project, milestone, '2026-03-15')
        self.assertEqual(milestone.last_task_deadline, date(2026, 3, 15))

    def test_last_task_deadline_empty_when_no_deadlines(self):
        project = self._create_project()
        milestone = self._create_milestone(project)
        self._create_task(project, milestone)
        self.assertFalse(milestone.last_task_deadline)

    def test_last_task_deadline_empty_when_no_tasks(self):
        project = self._create_project()
        milestone = self._create_milestone(project)
        self.assertFalse(milestone.last_task_deadline)

    def test_last_task_deadline_recomputes_when_task_deadline_changes(self):
        project = self._create_project()
        milestone = self._create_milestone(project)
        task = self._create_task(project, milestone, '2026-01-10')
        self.assertEqual(milestone.last_task_deadline, date(2026, 1, 10))
        task.date_deadline = '2026-04-05'
        self.assertEqual(milestone.last_task_deadline, date(2026, 4, 5))
