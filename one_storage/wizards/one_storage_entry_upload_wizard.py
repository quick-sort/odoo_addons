# Copyright 2026 One Storage
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

from odoo import _, fields, models
from odoo.exceptions import ValidationError


class OneStorageEntryUploadWizard(models.TransientModel):
    """Overwrite an existing file entry's content on its backend."""

    _name = "one.storage.entry.upload.wizard"
    _description = "One Storage Upload Wizard"

    entry_id = fields.Many2one(
        comodel_name="one.storage.entry",
        required=True,
        readonly=True,
        default=lambda self: self.env.context.get("default_entry_id"),
    )
    entry_name = fields.Char(related="entry_id.complete_name")
    datas = fields.Binary(string="File", required=True)
    filename = fields.Char()

    def action_apply(self):
        self.ensure_one()
        entry = self.entry_id
        if entry.is_dir:
            raise ValidationError(
                _("Cannot upload to a directory entry (%s).") % entry.display_name
            )
        if not self.datas:
            raise ValidationError(_("No file selected."))
        if self.filename:
            entry.name = self.filename
        entry.set_content(self.datas, binary=False)
        return {"type": "ir.actions.act_window_close"}
