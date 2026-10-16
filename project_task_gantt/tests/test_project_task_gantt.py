from datetime import datetime, timedelta

from odoo.tests.common import TransactionCase, tagged


@tagged('post_install', '-at_install')
class TestGanttTree(TransactionCase):

    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.start = datetime(2026, 5, 1, 9, 0, 0)

    def _make_task(self, name, project, start, parent=False):
        vals = {
            'name': name,
            'project_id': project.id,
            'task_start_date': start,
            'task_end_date': start + timedelta(days=1),
        }
        if parent:
            vals['parent_id'] = parent.id
        return self.env['project.task'].create(vals)

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

        self.assertEqual(len(data), 1)
        tasks = data[0]['tasks']
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

        tasks = data[0]['tasks']
        self.assertEqual([t['name'] for t in tasks], ['Child'])
        self.assertEqual(tasks[0]['depth'], 0)
