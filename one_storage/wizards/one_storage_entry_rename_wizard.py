# Copyright 2026 One Storage
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

from odoo import fields, models


class OneStorageEntryRenameWizard(models.TransientModel):
    """Rename an entry (logical tree + backend bytes)."""

    _name = "one.storage.entry.rename.wizard"
    _description = "One Storage Rename Wizard"

    entry_id = fields.Many2one(
        comodel_name="one.storage.entry",
        required=True,
        readonly=True,
        default=lambda self: self.env.context.get("default_entry_id"),
    )
    entry_name = fields.Char(related="entry_id.complete_name")
    new_name = fields.Char(required=True)

    def action_apply(self):
        self.ensure_one()
        self.entry_id.rename(self.new_name)
        return {"type": "ir.actions.act_window_close"}
