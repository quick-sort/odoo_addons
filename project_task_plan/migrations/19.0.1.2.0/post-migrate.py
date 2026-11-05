def migrate(cr, version):
    if not version:
        return

    # The field was removed from the model; Odoo does not drop the database
    # column on its own, so clean it up on upgrade.
    cr.execute(
        """
        SELECT 1
          FROM information_schema.columns
         WHERE table_name = 'project_task'
           AND column_name = 'lead_time'
        """
    )
    if cr.fetchone():
        cr.execute("ALTER TABLE project_task DROP COLUMN lead_time")
