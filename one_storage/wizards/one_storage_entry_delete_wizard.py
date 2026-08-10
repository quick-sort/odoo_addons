# Copyright 2026 One Storage
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

from odoo import fields, models


class OneStorageEntryDeleteWizard(models.TransientModel):
    """Confirm deletion of an entry (and its backend bytes for files)."""

    _name = "one.storage.entry.delete.wizard"
    _description = "One Storage Delete Wizard"

    entry_id = fields.Many2one(
        comodel_name="one.storage.entry",
        required=True,
        readonly=True,
        default=lambda self: self.env.context.get("default_entry_id"),
    )
    entry_name = fields.Char(related="entry_id.complete_name")
    is_dir = fields.Boolean(related="entry_id.is_dir")

    def action_apply(self):
        self.ensure_one()
        entry = self.entry_id
        entry.unlink()
        return {"type": "ir.actions.act_window_close"}
