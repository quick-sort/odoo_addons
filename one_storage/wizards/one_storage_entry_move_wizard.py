# Copyright 2026 One Storage
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

from odoo import fields, models


class OneStorageEntryMoveWizard(models.TransientModel):
    """Move entries (files or whole folders) into another folder."""

    _name = "one.storage.entry.move.wizard"
    _description = "One Storage Move Wizard"

    entry_ids = fields.Many2many(
        comodel_name="one.storage.entry",
        relation="one_storage_entry_move_wizard_entry_rel",
        default=lambda self: self.env.context.get("default_entry_ids", []),
    )
    entry_names = fields.Text(compute="_compute_entry_names")
    dest_dir_id = fields.Many2one(
        comodel_name="one.storage.entry",
        string="Destination Folder",
        domain=[("entry_type", "=", "directory")],
        required=True,
    )

    def _compute_entry_names(self):
        for wizard in self:
            wizard.entry_names = "\n".join(wizard.entry_ids.mapped("complete_name"))

    def action_apply(self):
        self.ensure_one()
        if self.entry_ids:
            self.env["one.storage.operation"].start_move(
                self.entry_ids, self.dest_dir_id
            )
        return {"type": "ir.actions.act_window_close"}
