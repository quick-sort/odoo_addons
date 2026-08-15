# Copyright 2026 One Storage
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

import base64

from odoo import _, fields, models
from odoo.exceptions import ValidationError


class OneStorageEntryCreateWizard(models.TransientModel):
    """Create a new folder and/or upload a file into the current folder."""

    _name = "one.storage.entry.create.wizard"
    _description = "One Storage Create Wizard"

    parent_id = fields.Many2one(
        comodel_name="one.storage.entry",
        required=True,
        readonly=True,
        default=lambda self: self.env.context.get("default_parent_id")
        or self.env["one.storage.entry"]._get_or_create_root().id,
    )
    parent_name = fields.Char(related="parent_id.complete_name")
    folder_name = fields.Char(
        help="Leave empty unless you want to create a new subfolder here."
    )
    datas = fields.Binary(string="File")
    filename = fields.Char()

    def action_apply(self):
        self.ensure_one()
        parent = self.parent_id
        if not parent.is_dir:
            raise ValidationError(
                _("Destination '%s' is not a folder.", parent.display_name)
            )
        created = None
        if self.folder_name and self.folder_name.strip():
            created = parent.mkdir(self.folder_name.strip())
        if self.datas:
            target = created if created else parent
            name = self.filename or "file"
            existing = self.env["one.storage.entry"].search(
                [("parent_id", "=", target.id), ("name", "=", name)], limit=1
            )
            if existing:
                if existing.is_dir:
                    raise ValidationError(
                        _("A folder named '%s' already exists here.", name)
                    )
                existing.set_content(self.datas, binary=False)
            else:
                created = target.create_file(name, base64.b64decode(self.datas))
        if not created and not self.datas:
            raise ValidationError(
                _("Enter a folder name or select a file to upload.")
            )
        return {"type": "ir.actions.act_window_close"}
