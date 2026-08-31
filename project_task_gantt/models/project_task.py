from odoo import models, fields, api
from odoo.osv import expression
from odoo.exceptions import ValidationError
import logging

_logger = logging.getLogger(__name__)


class ProjectTask(models.Model):
    _inherit = 'project.task'

    task_start_date = fields.Datetime(
        string='Start Date',
        tracking=True,
        copy=False,
        default=fields.Datetime.now,
        help="Start date for Gantt chart visualization"
    )
    task_end_date = fields.Datetime(
        string='End Date',
        tracking=True,
        copy=False,
        help="End date for Gantt chart visualization"
    )
    gantt_duration = fields.Float(
        string='Duration (Days)',
        compute='_compute_gantt_duration',
        store=True,
        help="Calculated duration between start and end dates"
    )

    def _parse_datetime_string(self, date_string):
        """
        Parse various datetime string formats to Odoo datetime
        Handles ISO 8601 format with milliseconds and timezone
        """
        if not isinstance(date_string, str):
            return date_string

        try:
            # Remove milliseconds: .000Z or .123Z
            date_string = date_string.split('.')[0]
            # Remove timezone indicator
            date_string = date_string.replace('Z', '').replace('z', '')
            # Remove 'T' separator if present
            date_string = date_string.replace('T', ' ')

            # Try to parse the datetime
            return fields.Datetime.from_string(date_string)
        except Exception as e:
            _logger.error(f"Failed to parse datetime string '{date_string}': {e}")
            raise ValidationError(f"Invalid datetime format: {date_string}")

    def _sync_date_fields(self, vals):
        """
        Synchronize all date fields to ensure consistency
        """
        # Sync task_end_date with date_deadline - always copy exact datetime
        if vals.get('task_end_date'):
            if 'date_deadline' not in vals:
                vals['date_deadline'] = vals['task_end_date']
            # Also sync with date_end if it exists, keeping exact same datetime
            if hasattr(self, 'date_end') and 'date_end' not in vals:
                vals['date_end'] = vals['task_end_date']

        # Sync date_deadline with task_end_date - always copy exact datetime
        if vals.get('date_deadline') and 'task_end_date' not in vals:
            vals['task_end_date'] = vals['date_deadline']
            # Also sync with date_end if it exists
            if hasattr(self, 'date_end') and 'date_end' not in vals:
                vals['date_end'] = vals['date_deadline']

        # Sync task_start_date with date_start
        if vals.get('task_start_date'):
            if hasattr(self, 'date_start') and 'date_start' not in vals:
                vals['date_start'] = vals['task_start_date']

    @api.depends('task_start_date', 'task_end_date')
    def _compute_gantt_duration(self):
        """Compute the duration in days between start and end dates"""
        for task in self:
            if task.task_start_date and task.task_end_date:
                delta = task.task_end_date - task.task_start_date
                task.gantt_duration = delta.total_seconds() / 86400.0
            else:
                task.gantt_duration = 0.0

    @api.onchange('task_end_date')
    def _onchange_task_end_date_updates_deadline(self):
        """Synchronize task_end_date with deadline field"""
        if self.task_end_date:
            # Always copy the exact datetime to deadline to preserve time
            self.date_deadline = self.task_end_date
            # Also sync with date_end if it exists, keeping exact same datetime
            if hasattr(self, 'date_end'):
                self.date_end = self.task_end_date

    @api.onchange('date_deadline')
    def _onchange_deadline_updates_task_end_date(self):
        """Synchronize deadline with task_end_date field"""
        if self.date_deadline:
            # Always copy the exact datetime to preserve time
            self.task_end_date = self.date_deadline
            # Also sync with date_end if it exists
            if hasattr(self, 'date_end'):
                self.date_end = self.task_end_date

    # @api.constrains('task_start_date', 'task_end_date')
    # def _check_dates(self):
    #     """Validate that end date is not before start date"""
    #     for task in self:
    #         if task.task_start_date and task.task_end_date:
    #             if task.task_end_date < task.task_start_date:
    #                 raise ValidationError(
    #                     'The end date of task "%s" cannot be before its start date.' % task.name
    #                 )

    @api.model_create_multi
    def create(self, vals_list):
        """Override create to sync deadline with task_end_date"""
        for vals in vals_list:
            try:
                # Parse datetime strings first
                if vals.get('task_end_date'):
                    vals['task_end_date'] = self._parse_datetime_string(vals['task_end_date'])

                if vals.get('task_start_date'):
                    vals['task_start_date'] = self._parse_datetime_string(vals['task_start_date'])

                # Synchronize all date fields
                self._sync_date_fields(vals)

            except Exception as e:
                _logger.error(f"Error processing dates in create: {str(e)}", exc_info=True)
                raise ValidationError(f"Invalid date format: {str(e)}")

        return super().create(vals_list)

    def write(self, vals):
        """Override write to sync deadline with task_end_date"""
        try:
            # Parse datetime strings first
            if vals.get('task_end_date'):
                vals['task_end_date'] = self._parse_datetime_string(vals['task_end_date'])

            if vals.get('task_start_date'):
                vals['task_start_date'] = self._parse_datetime_string(vals['task_start_date'])

            # Synchronize all date fields
            self._sync_date_fields(vals)

        except Exception as e:
            _logger.error(f"Error processing dates in write: {str(e)}", exc_info=True)
            raise ValidationError(f"Invalid date format: {str(e)}")

        return super().write(vals)

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

            # Only show tasks with both start and end dates
            gantt_domain = expression.AND([
                domain,
                [('task_start_date', '!=', False), ('task_end_date', '!=', False)]
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
                'task_start_date',
                'task_end_date',
                'color',
                'priority',
                'description',
                group_by
            ]

            # Add progress field if it exists (might not exist in all Odoo versions)
            if 'progress' in self.env['project.task']._fields:
                fields_to_read.append('progress')

            tasks_data = self.search_read(gantt_domain, fields_to_read, order='task_start_date asc')

            if not tasks_data:
                _logger.info("No tasks found matching criteria")
                return []

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

            for task in tasks_data:
                raw_value = task.get(group_by)

                # Build task payload
                task_dict = {
                    'id': task['id'],
                    'name': task['name'],
                    'start_date': task['task_start_date'].isoformat() if task['task_start_date'] else None,
                    'end_date': task['task_end_date'].isoformat() if task['task_end_date'] else None,
                    'progress': task.get('progress', 0) or 0,
                    'color': task.get('color', 0) or 0,
                    'priority': task.get('priority', '0'),
                    'description': task.get('description', '') or '',
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

            # Sort groups by name and return as list
            result = sorted(grouped_data.values(), key=lambda x: x['name'])

            _logger.info(f"Gantt data loaded: {len(result)} groups, {sum(len(g['tasks']) for g in result)} tasks")

            return result

        except Exception as e:
            _logger.error(f"Error in get_gantt_data: {str(e)}", exc_info=True)
            # Return empty list instead of raising to prevent frontend crash
            return []

    def action_open_gantt_view(self):
        """Action to open Gantt view for current task's project"""
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': 'Project Gantt Chart',
            'res_model': 'project.task',
            'view_mode': 'gantt,list,form',
            'domain': [('project_id', '=', self.project_id.id)],
            'context': {'group_by': 'stage_id'},
        }

    def action_sync_dates(self):
        """Action to manually sync all date fields for current task"""
        self.ensure_one()
        vals = {}

        # Sync task_end_date with date_deadline
        if self.task_end_date and self.date_deadline:
            if self.task_end_date.date() != self.date_deadline:
                vals['date_deadline'] = self.task_end_date.date()

        # Sync date_deadline with task_end_date
        if self.date_deadline and self.task_end_date:
            if self.task_end_date.date() != self.date_deadline:
                # Preserve existing time
                deadline_datetime = fields.Datetime.to_datetime(self.date_deadline)
                vals['task_end_date'] = deadline_datetime.replace(
                    hour=self.task_end_date.hour,
                    minute=self.task_end_date.minute,
                    second=self.task_end_date.second
                )

        if vals:
            self.write(vals)
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'Dates Synchronized',
                    'message': 'All date fields have been synchronized.',
                    'type': 'success',
                }
            }
        else:
            return {
                'type': 'ir.actions.client',
                'tag': 'display_notification',
                'params': {
                    'title': 'No Changes Needed',
                    'message': 'All date fields are already synchronized.',
                    'type': 'info',
                }
            }
