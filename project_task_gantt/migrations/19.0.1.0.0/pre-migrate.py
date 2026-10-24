def migrate(cr, version):
    if not version:
        return

    # task_end_date is removed in favor of core date_deadline. Copy any value
    # that only ever lived in the old column before the model stops managing it.
    cr.execute(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name = 'project_task' AND column_name = 'task_end_date'"
    )
    if cr.fetchone():
        cr.execute(
            """
            UPDATE project_task
               SET date_deadline = task_end_date
             WHERE date_deadline IS NULL
               AND task_end_date IS NOT NULL
            """
        )

    # gantt_duration is a stored computed field; refresh it from the new
    # dependency (date_deadline) instead of the removed column.
    cr.execute(
        """
        UPDATE project_task
           SET gantt_duration = CASE
               WHEN task_start_date IS NOT NULL AND date_deadline IS NOT NULL
               THEN EXTRACT(EPOCH FROM (date_deadline - task_start_date)) / 86400.0
               ELSE 0.0
           END
        """
    )
