from datetime import date, timedelta
from unittest.mock import patch

from odoo.tests import tagged
from odoo.tests.common import TransactionCase


@tagged("post_install", "-at_install")
class TestProjectActivityNotify(TransactionCase):

    def setUp(self):
        super().setUp()
        self.activity_type = self.env['mail.activity.type'].create({
            'name': 'Test Activity',
        })

    def _create_project(self, days):
        return self.env['project.project'].create({
            'name': 'Test Project',
            'activity_reminder_days': days,
        })

    def _create_task(self, project):
        return self.env['project.task'].create({
            'name': 'Test Task',
            'project_id': project.id,
        })

    def _create_activity(self, res_model, res_id, deadline):
        return self.env['mail.activity'].create({
            'res_model_id': self.env['ir.model']._get(res_model).id,
            'res_id': res_id,
            'activity_type_id': self.activity_type.id,
            'date_deadline': deadline,
            'summary': 'Test Activity',
            'user_id': self.env.user.id,
        })

    def test_remind_task_and_project_activities(self):
        project = self._create_project(3)
        task = self._create_task(project)
        target = date.today() + timedelta(days=3)
        task_activity = self._create_activity('project.task', task.id, target)
        project_activity = self._create_activity('project.project', project.id, target)

        self.env['mail.activity']._cron_remind_activities()

        self.assertTrue(task_activity.reminder_sent)
        self.assertTrue(project_activity.reminder_sent)

    def test_ignore_non_matching_deadline(self):
        project = self._create_project(3)
        task = self._create_task(project)
        activity = self._create_activity('project.task', task.id, date.today() + timedelta(days=4))

        self.env['mail.activity']._cron_remind_activities()

        self.assertFalse(activity.reminder_sent)

    def test_ignore_disabled_project(self):
        project = self._create_project(0)
        task = self._create_task(project)
        activity = self._create_activity('project.task', task.id, date.today())

        self.env['mail.activity']._cron_remind_activities()

        self.assertFalse(activity.reminder_sent)

    def test_remind_only_once(self):
        project = self._create_project(3)
        task = self._create_task(project)
        activity = self._create_activity('project.task', task.id, date.today() + timedelta(days=3))

        ActivityModel = type(self.env['mail.activity'])
        with patch.object(ActivityModel, 'action_notify', return_value=None) as mocked:
            self.env['mail.activity']._cron_remind_activities()
            self.assertEqual(mocked.call_count, 1)
            self.assertTrue(activity.reminder_sent)

            self.env['mail.activity']._cron_remind_activities()
            self.assertEqual(mocked.call_count, 1)
