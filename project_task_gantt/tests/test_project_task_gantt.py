from datetime import date, datetime, timedelta

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestGanttTree(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.start = datetime(2026, 5, 1, 9, 0, 0)

    def _make_task(self, name, project, start, parent=False, sequence=False):
        vals = {
            'name': name,
            'project_id': project.id,
            'task_start_date': start,
            'date_deadline': start + timedelta(days=1),
        }
        if parent:
            vals['parent_id'] = parent.id
        if sequence is not False:
            vals['sequence'] = sequence
        return self.env['project.task'].create(vals)

    def _make_milestone(self, name, project, deadline=None, is_reached=False):
        return self.env['project.milestone'].create({
            'name': name,
            'project_id': project.id,
            'deadline': deadline,
            'is_reached': is_reached,
        })

    def _task_names(self, project):
        data = self.env['project.task'].get_gantt_data(
            domain=[('project_id', '=', project.id)],
            group_by='project_id',
        )
        return [t['name'] for t in data['groups'][0]['tasks']]

    def test_get_gantt_data_tree_order_and_depth(self):
        project = self.env['project.project'].create({'name': 'Tree Project'})

        parent = self._make_task('Parent', project, self.start)
        child = self._make_task('Child', project, self.start + timedelta(days=2), parent)
        grandchild = self._make_task('Grandchild', project, self.start + timedelta(days=4), child)
        self._make_task('Root2', project, self.start + timedelta(days=6))

        data = self.env['project.task'].get_gantt_data(
            domain=[('project_id', '=', project.id)],
            group_by='project_id',
        )

        self.assertEqual(len(data['groups']), 1)
        tasks = data['groups'][0]['tasks']
        by_name = {t['name']: t for t in tasks}

        self.assertEqual(set(by_name), {'Parent', 'Child', 'Grandchild', 'Root2'})
        self.assertEqual(by_name['Parent']['depth'], 0)
        self.assertEqual(by_name['Child']['depth'], 1)
        self.assertEqual(by_name['Grandchild']['depth'], 2)
        self.assertEqual(by_name['Root2']['depth'], 0)

        # DFS pre-order: a parent must come before its descendants
        names = [t['name'] for t in tasks]
        self.assertLess(names.index('Parent'), names.index('Child'))
        self.assertLess(names.index('Child'), names.index('Grandchild'))

    def test_order_follows_sequence_not_start_date(self):
        project = self.env['project.project'].create({'name': 'Sequence Project'})

        self._make_task('Second', project, self.start, sequence=20)
        self._make_task('First', project, self.start + timedelta(days=2), sequence=10)

        self.assertEqual(self._task_names(project), ['First', 'Second'])

    def test_order_stable_when_dates_change(self):
        project = self.env['project.project'].create({'name': 'Stable Project'})

        self._make_task('First', project, self.start)
        second = self._make_task('Second', project, self.start + timedelta(days=2))

        # Same sequence: id breaks the tie
        self.assertEqual(self._task_names(project), ['First', 'Second'])

        # Simulate a gantt drag: only dates change, rows must not reorder
        second.write({
            'gantt_date_start': self.start - timedelta(days=5),
            'gantt_date_stop': self.start - timedelta(days=4),
        })
        self.assertEqual(self._task_names(project), ['First', 'Second'])
        self.assertEqual(second.task_start_date, self.start - timedelta(days=5))
        self.assertEqual(second.date_deadline, self.start - timedelta(days=4))

    def test_subtask_with_parent_filtered_out_is_root(self):
        project = self.env['project.project'].create({'name': 'Filtered Project'})

        parent = self._make_task('Parent', project, self.start)
        child = self._make_task(
            'Child', project, self.start + timedelta(days=2), parent
        )

        # Only the child matches the domain; its parent is not in the result
        # set, so the child must be treated as a top-level task (depth 0).
        data = self.env['project.task'].get_gantt_data(
            domain=[('id', '=', child.id)],
            group_by='project_id',
        )

        tasks = data['groups'][0]['tasks']
        self.assertEqual([t['name'] for t in tasks], ['Child'])
        self.assertEqual(tasks[0]['depth'], 0)

    def test_get_gantt_data_includes_assignees(self):
        project = self.env['project.project'].create({'name': 'Assignee Project'})
        task = self._make_task('Assigned', project, self.start)
        task.user_ids = [(6, 0, self.env.user.ids)]

        data = self.env['project.task'].get_gantt_data(
            domain=[('project_id', '=', project.id)],
            group_by='project_id',
        )

        self.assertEqual(
            data['groups'][0]['tasks'][0]['assignees'],
            [self.env.user.display_name],
        )

    def test_gantt_alias_reads_backing_fields(self):
        project = self.env['project.project'].create({'name': 'Alias Project'})
        task = self._make_task('Aliased', project, self.start)

        self.assertEqual(task.gantt_date_start, task.task_start_date)
        self.assertEqual(task.gantt_date_stop, task.date_deadline)

    def test_gantt_alias_write_updates_backing_fields(self):
        project = self.env['project.project'].create({'name': 'Alias Write Project'})
        task = self._make_task('Aliased', project, self.start)
        new_start = self.start + timedelta(days=3)
        new_stop = self.start + timedelta(days=4)

        task.write({
            'gantt_date_start': new_start,
            'gantt_date_stop': new_stop,
        })

        self.assertEqual(task.task_start_date, new_start)
        self.assertEqual(task.date_deadline, new_stop)
        self.assertEqual(task.gantt_duration, 1.0)

    def test_gantt_alias_write_leaves_date_end_untouched(self):
        project = self.env['project.project'].create({'name': 'Completion Project'})
        task = self._make_task('Completed', project, self.start)
        completed = datetime(2026, 6, 1, 12, 0, 0)
        task.write({'date_end': completed})

        task.write({
            'gantt_date_start': self.start + timedelta(days=1),
            'gantt_date_stop': self.start + timedelta(days=2),
        })

        self.assertEqual(task.date_end, completed)

    def test_date_deadline_write_shows_in_gantt_stop(self):
        project = self.env['project.project'].create({'name': 'Deadline Project'})
        task = self._make_task('Deadline', project, self.start)
        new_deadline = self.start + timedelta(days=9)

        task.write({'date_deadline': new_deadline})

        self.assertEqual(task.gantt_date_stop, new_deadline)

    def test_search_on_gantt_date_aliases(self):
        project = self.env['project.project'].create({'name': 'Search Project'})
        scheduled = self._make_task('Scheduled', project, self.start)
        unscheduled = self.env['project.task'].create({
            'name': 'Unscheduled',
            'project_id': project.id,
            'task_start_date': False,
            'date_deadline': False,
        })

        found = self.env['project.task'].search([
            ('project_id', '=', project.id),
            ('gantt_date_start', '>=', self.start),
        ])
        self.assertIn(scheduled, found)
        self.assertNotIn(unscheduled, found)

        with_stop = self.env['project.task'].search([
            ('project_id', '=', project.id),
            ('gantt_date_stop', '!=', False),
        ])
        self.assertIn(scheduled, with_stop)
        self.assertNotIn(unscheduled, with_stop)

    def test_default_get_maps_gantt_start_to_backing_field(self):
        task_model = self.env['project.task'].with_context(
            default_gantt_date_start='2026-05-01 09:00:00'
        )

        defaults = task_model.default_get(['task_start_date', 'gantt_date_start'])

        self.assertNotIn('gantt_date_start', defaults)
        self.assertEqual(
            defaults['task_start_date'],
            datetime(2026, 5, 1, 9, 0, 0),
        )

    def test_explicit_backing_default_wins_over_alias(self):
        task_model = self.env['project.task'].with_context(
            default_gantt_date_start='2026-05-01 09:00:00',
            default_task_start_date='2026-06-01 00:00:00',
        )

        defaults = task_model.default_get(['task_start_date', 'gantt_date_start'])

        self.assertNotIn('gantt_date_start', defaults)
        self.assertEqual(
            defaults['task_start_date'],
            datetime(2026, 6, 1, 0, 0, 0),
        )

    def test_task_end_date_is_compat_alias_of_deadline(self):
        project = self.env['project.project'].create({'name': 'Compat Project'})
        task = self._make_task('Compat', project, self.start)
        new_deadline = self.start + timedelta(days=7)

        self.assertFalse(task._fields['task_end_date'].store)
        self.assertEqual(task.task_end_date, task.date_deadline)

        task.write({'task_end_date': new_deadline})

        self.assertEqual(task.date_deadline, new_deadline)
        self.assertIn(
            task,
            self.env['project.task'].search([
                ('project_id', '=', project.id),
                ('task_end_date', '>=', new_deadline),
            ]),
        )

    def test_get_gantt_data_end_date_uses_deadline(self):
        project = self.env['project.project'].create({'name': 'Payload Project'})
        task = self._make_task('Payload', project, self.start)

        data = self.env['project.task'].get_gantt_data(
            domain=[('project_id', '=', project.id)],
            group_by='project_id',
        )

        payload = data['groups'][0]['tasks'][0]
        self.assertEqual(payload['start_date'], task.task_start_date.isoformat())
        self.assertEqual(payload['end_date'], task.date_deadline.isoformat())

    def test_get_gantt_data_returns_groups_and_markers(self):
        project = self.env['project.project'].create({'name': 'Contract Project'})
        self._make_task('Contract', project, self.start)

        data = self.env['project.task'].get_gantt_data(
            domain=[('project_id', '=', project.id)],
            group_by='project_id',
        )

        self.assertEqual(set(data), {'groups', 'markers'})
        self.assertEqual([t['name'] for t in data['groups'][0]['tasks']], ['Contract'])
        self.assertEqual(data['markers'], [])

    def test_markers_include_milestones_with_deadline(self):
        project = self.env['project.project'].create({'name': 'Marker Project'})
        self._make_task('Marker Task', project, self.start)
        self._make_milestone('Launch', project, date(2026, 6, 15))

        markers = self.env['project.task'].get_gantt_data(
            domain=[('project_id', '=', project.id)],
            group_by='project_id',
        )['markers']

        self.assertEqual(len(markers), 1)
        self.assertEqual(markers[0]['date'], '2026-06-15')
        self.assertEqual(markers[0]['label'], 'Launch')

    def test_markers_exclude_milestone_without_deadline(self):
        project = self.env['project.project'].create({'name': 'No Deadline Project'})
        self._make_task('No Deadline Task', project, self.start)
        self._make_milestone('Undated', project)

        markers = self.env['project.task'].get_gantt_data(
            domain=[('project_id', '=', project.id)],
            group_by='project_id',
        )['markers']

        self.assertEqual(markers, [])

    def test_markers_exclude_milestones_of_projects_outside_domain(self):
        project_a = self.env['project.project'].create({'name': 'Domain A'})
        project_b = self.env['project.project'].create({'name': 'Domain B'})
        self._make_task('Task A', project_a, self.start)
        self._make_milestone('Outside', project_b, date(2026, 6, 15))

        markers = self.env['project.task'].get_gantt_data(
            domain=[('project_id', '=', project_a.id)],
            group_by='project_id',
        )['markers']

        self.assertEqual(markers, [])

    def test_marker_color_and_description_reflect_is_reached(self):
        project = self.env['project.project'].create({'name': 'Reached Project'})
        self._make_task('Reached Task', project, self.start)
        self._make_milestone('Done', project, date(2026, 6, 1), is_reached=True)
        self._make_milestone('Pending', project, date(2026, 6, 2))

        markers = self.env['project.task'].get_gantt_data(
            domain=[('project_id', '=', project.id)],
            group_by='project_id',
        )['markers']
        by_label = {m['label']: m for m in markers}

        self.assertEqual(by_label['Done']['color'], '#adb5bd')
        self.assertEqual(by_label['Done']['description'], 'Reached')
        self.assertEqual(by_label['Pending']['color'], '#71639e')
        self.assertEqual(by_label['Pending']['description'], 'Unreached')

    def test_markers_are_project_scoped_when_grouping_by_user(self):
        project = self.env['project.project'].create({'name': 'User Group Project'})
        task = self._make_task('Grouped', project, self.start)
        task.user_ids = [(6, 0, self.env.user.ids)]
        self._make_milestone('Grouped Milestone', project, date(2026, 6, 3))

        data = self.env['project.task'].get_gantt_data(
            domain=[('project_id', '=', project.id)],
            group_by='user_ids',
        )

        self.assertEqual(len(data['markers']), 1)
        self.assertEqual(data['markers'][0]['label'], 'Grouped Milestone')

    def test_markers_not_duplicated_for_multi_group_tasks(self):
        project = self.env['project.project'].create({'name': 'Multi Group Project'})
        other_user = self.env['res.users'].create({
            'name': 'Other User',
            'login': 'other_gantt_user',
        })
        task = self._make_task('Shared', project, self.start)
        task.user_ids = [(6, 0, (self.env.user | other_user).ids)]
        self._make_milestone('Shared Milestone', project, date(2026, 6, 4))

        data = self.env['project.task'].get_gantt_data(
            domain=[('project_id', '=', project.id)],
            group_by='user_ids',
        )

        self.assertEqual(len(data['markers']), 1)

    def test_markers_empty_when_no_tasks(self):
        data = self.env['project.task'].get_gantt_data(
            domain=[('id', '=', 0)],
            group_by='project_id',
        )

        self.assertEqual(data, {'groups': [], 'markers': []})

    def test_markers_empty_for_private_task_without_project(self):
        task = self.env['project.task'].create({
            'name': 'Private',
            'project_id': False,
            'task_start_date': self.start,
            'date_deadline': self.start + timedelta(days=1),
        })

        data = self.env['project.task'].get_gantt_data(
            domain=[('id', '=', task.id)],
            group_by='project_id',
        )

        self.assertEqual(data['markers'], [])
