import logging

from odoo import api, fields, models
from odoo.fields import Domain

_logger = logging.getLogger(__name__)


class ProjectTask(models.Model):
    _name = 'project.task'
    _inherit = ['project.task', 'gantt.mixin']

    task_start_date = fields.Datetime(
        string='Start Date',
        tracking=True,
        copy=False,
        default=fields.Datetime.now,
        help="Start date for Gantt chart visualization"
    )
    gantt_duration = fields.Float(
        string='Duration (Days)',
        compute='_compute_gantt_duration',
        store=True,
        help="Calculated duration between start and end dates"
    )
    task_end_date = fields.Datetime(
        string='End Date',
        compute='_compute_task_end_date',
        inverse='_inverse_task_end_date',
        search='_search_task_end_date',
        help="Deprecated alias of Deadline, kept for existing views.",
    )

    def _gantt_date_fields(self):
        # date_deadline is the single source of truth for the gantt end date;
        # core date_end is the completion timestamp and is left untouched.
        return ('task_start_date', 'date_deadline')

    @api.depends('date_deadline')
    def _compute_task_end_date(self):
        for task in self:
            task.task_end_date = task.date_deadline

    def _inverse_task_end_date(self):
        for task in self:
            if task.task_end_date != task.date_deadline:
                task.write({'date_deadline': task.task_end_date})

    def _search_task_end_date(self, operator, value):
        return [('date_deadline', operator, value)]

    @api.depends('task_start_date', 'date_deadline')
    def _compute_gantt_duration(self):
        """Compute the duration in days between start and end dates"""
        for task in self:
            if task.task_start_date and task.date_deadline:
                delta = task.date_deadline - task.task_start_date
                task.gantt_duration = delta.total_seconds() / 86400.0
            else:
                task.gantt_duration = 0.0

    @api.model
    def _gantt_progress_pct(self, ratio):
        """Convert ``project.task.progress`` (hr_timesheet 0..1 ratio) to 0..100%.

        ``progress`` is hours spent over allocated hours, so it is a ratio and
        may exceed 1.0 when over-allocated. The generic gantt renderer expects a
        percentage; overtime values are kept (the renderer clamps the bar width).
        """
        return round((ratio or 0.0) * 100, 2)

    @api.model
    def get_gantt_data(self, domain=None, group_by='project_id'):
        """
        Fetch and group tasks for Gantt chart display

        Args:
            domain: Search domain to filter tasks
            group_by: Field name to group tasks by

        Returns:
            List of dictionaries with grouped task data
        """
        try:
            domain = domain or []

            # Show tasks with a start date; the end date is optional (the
            # frontend falls back to start + 1 day when it is missing).
            start_field, _stop_field = self._gantt_date_fields()
            gantt_domain = Domain.AND([
                domain,
                [(start_field, '!=', False)]
            ])

            # Validate group_by field
            valid_group_fields = ['project_id', 'user_ids', 'stage_id', 'priority', 'partner_id']
            if group_by not in valid_group_fields:
                _logger.warning(f"Invalid group_by field '{group_by}', defaulting to 'project_id'")
                group_by = 'project_id'

            # Ensure field exists and is stored
            if group_by not in self.env['project.task']._fields:
                group_by = 'project_id'
            elif not self.env['project.task']._fields[group_by].store:
                group_by = 'project_id'

            # Fields to read from tasks
            fields_to_read = [
                'name',
                'gantt_date_start',
                'gantt_date_stop',
                'color',
                'priority',
                'description',
                'parent_id',
                'user_ids',
                group_by
            ]
            if 'project_id' not in fields_to_read:
                # Needed to derive milestone markers regardless of the grouping.
                fields_to_read.append('project_id')

            # Add progress field if it exists (might not exist in all Odoo versions)
            if 'progress' in self.env['project.task']._fields:
                fields_to_read.append('progress')

            # Order by sequence, not dates, so dragging a bar only moves it in
            # time without reordering the row list; id breaks ties.
            tasks_data = self.search_read(gantt_domain, fields_to_read, order='sequence asc, id asc')

            if not tasks_data:
                _logger.info("No tasks found matching criteria")
                return {'groups': [], 'markers': []}

            project_ids = {
                task['project_id'][0]
                for task in tasks_data
                if task.get('project_id')
            }
            markers = self._get_gantt_markers(project_ids)

            # Group tasks by the specified field with proper handling of many2many and selections
            grouped_data = {}

            field_def = self.env['project.task']._fields.get(group_by)
            field_type = getattr(field_def, 'type', 'char')
            selection_map = {}
            if field_type == 'selection' and getattr(field_def, 'selection', None):
                selection_map = dict(field_def.selection)

            def add_to_group(g_key, g_name, t):
                if g_key not in grouped_data:
                    grouped_data[g_key] = {
                        'id': g_key,
                        'name': g_name,
                        'tasks': []
                    }
                grouped_data[g_key]['tasks'].append(t)

            # Preload names for many2many user_ids when needed
            def resolve_m2m_names(model_name, ids):
                if not ids:
                    return {}
                records = self.env[model_name].sudo().browse(ids)
                return {rec.id: rec.display_name for rec in records}

            def normalize_m2m_ids(raw):
                # search_read returns m2m values as plain ids; tolerate
                # (id, name) pairs as well.
                return [
                    value[0] if isinstance(value, (list, tuple)) else value
                    for value in (raw or [])
                ]

            # Collect ids for potential m2m lookup first pass
            m2m_ids = set()
            if field_type == 'many2many':
                for task in tasks_data:
                    raw = task.get(group_by) or []
                    if raw and isinstance(raw, list) and (len(raw) == 0 or isinstance(raw[0], int)):
                        m2m_ids.update(raw)

            id_to_name = {}
            if field_type == 'many2many':
                model_map = {
                    'user_ids': 'res.users',
                    'partner_id': 'res.partner',
                }
                model_name = model_map.get(group_by, 'res.users')
                id_to_name = resolve_m2m_names(model_name, list(m2m_ids))

            assignee_ids = set()
            for task in tasks_data:
                assignee_ids.update(normalize_m2m_ids(task.get('user_ids')))
            assignee_names = resolve_m2m_names('res.users', list(assignee_ids))

            for task in tasks_data:
                raw_value = task.get(group_by)

                # Build task payload
                task_dict = {
                    'id': task['id'],
                    'name': task['name'],
                    'start_date': task['gantt_date_start'].isoformat() if task['gantt_date_start'] else None,
                    'end_date': task['gantt_date_stop'].isoformat() if task['gantt_date_stop'] else None,
                    'progress': self._gantt_progress_pct(task.get('progress')),
                    'color': task.get('color', 0) or 0,
                    'priority': task.get('priority', '0'),
                    'description': task.get('description', '') or '',
                    'parent_id': task['parent_id'][0] if task.get('parent_id') else False,
                    'assignees': [
                        assignee_names.get(user_id, f"ID {user_id}")
                        for user_id in normalize_m2m_ids(task.get('user_ids'))
                    ],
                }

                if field_type == 'many2one':
                    if raw_value:
                        g_key = raw_value[0]
                        g_name = raw_value[1]
                    else:
                        g_key = 'unassigned'
                        g_name = 'Unassigned'
                    add_to_group(g_key, g_name, task_dict)

                elif field_type == 'many2many':
                    ids_list = []
                    if raw_value and isinstance(raw_value, list):
                        if raw_value and isinstance(raw_value[0], int):
                            ids_list = raw_value
                        elif raw_value and isinstance(raw_value[0], (list, tuple)):
                            ids_list = [rid[0] for rid in raw_value if rid]
                    if not ids_list:
                        add_to_group('unassigned', 'Unassigned', task_dict)
                    else:
                        for rid in ids_list:
                            g_key = f"{group_by}:{rid}"
                            g_name = id_to_name.get(rid, f"ID {rid}")
                            add_to_group(g_key, g_name, task_dict)

                elif field_type == 'selection':
                    key = raw_value if raw_value is not False else 'unassigned'
                    label = selection_map.get(raw_value, 'Unassigned') if raw_value else 'Unassigned'
                    add_to_group(str(key), label, task_dict)

                else:
                    # Char, integer, etc.
                    if not raw_value:
                        add_to_group('unassigned', 'Unassigned', task_dict)
                    else:
                        add_to_group(str(raw_value), str(raw_value).replace('_', ' ').title(), task_dict)

            # Order each group's tasks as a DFS tree and annotate depth
            for group in grouped_data.values():
                group['tasks'] = self._order_task_tree(group['tasks'])

            # Sort groups by name and return as list
            result = sorted(grouped_data.values(), key=lambda x: x['name'])

            _logger.info(f"Gantt data loaded: {len(result)} groups, {sum(len(g['tasks']) for g in result)} tasks, {len(markers)} markers")

            return {'groups': result, 'markers': markers}

        except Exception as e:
            _logger.error(f"Error in get_gantt_data: {str(e)}", exc_info=True)
            # Return an empty payload instead of raising to prevent a frontend crash
            return {'groups': [], 'markers': []}

    def _get_gantt_markers(self, project_ids):
        """Milestone deadlines of the given projects, as generic gantt markers.

        The search is not sudoed, so milestone record rules apply.
        """
        if not project_ids:
            return []
        milestones = self.env['project.milestone'].search(
            [
                ('project_id', 'in', list(project_ids)),
                ('deadline', '!=', False),
            ],
            order='deadline asc, sequence asc, id asc',
        )
        return [
            {
                'date': milestone.deadline.isoformat(),
                'label': milestone.name,
                'color': '#adb5bd' if milestone.is_reached else '#71639e',
                'description': 'Reached' if milestone.is_reached else 'Unreached',
            }
            for milestone in milestones
        ]

    def _order_task_tree(self, tasks):
        """Order tasks in DFS pre-order and annotate each with its tree depth.

        A task whose parent is not in the same list is treated as a root
        (depth 0), so a subtask grouped apart from its parent still shows.
        Roots and siblings keep the input order (sequence asc, id asc).
        """
        ids = {t['id'] for t in tasks}
        children = {}
        for t in tasks:
            pid = t.get('parent_id')
            if pid and pid in ids:
                children.setdefault(pid, []).append(t)

        ordered = []
        visited = set()

        def visit(task, depth):
            if task['id'] in visited:
                return
            visited.add(task['id'])
            task['depth'] = depth
            ordered.append(task)
            for child in children.get(task['id'], []):
                visit(child, depth + 1)

        for t in tasks:
            if not t.get('parent_id') or t['parent_id'] not in ids:
                visit(t, 0)

        # Safety net for any task not reached (e.g. unexpected cycle)
        for t in tasks:
            visit(t, 0)

        return ordered
