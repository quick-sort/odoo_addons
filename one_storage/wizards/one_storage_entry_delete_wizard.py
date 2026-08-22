# Copyright 2026 One Storage
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class OneStorageEntryDeleteWizard(models.TransientModel):
    """Confirm deletion of entries (and their backend bytes for files)."""

    _name = "one.storage.entry.delete.wizard"
    _description = "One Storage Delete Wizard"

    entry_ids = fields.Many2many(
        comodel_name="one.storage.entry",
        relation="one_storage_entry_delete_wizard_entry_rel",
        default=lambda self: self.env.context.get("default_entry_ids", []),
    )
    entry_names = fields.Text(compute="_compute_entry_names")
    has_dir = fields.Boolean(compute="_compute_entry_names")
    recursive = fields.Boolean(
        string="Delete folders recursively",
        help="Delete folders together with everything they contain. Without "
        "this, only empty folders can be deleted.",
    )

    @api.depends("entry_ids")
    def _compute_entry_names(self):
        for wizard in self:
            entries = wizard.entry_ids
            wizard.entry_names = "\n".join(entries.mapped("complete_name"))
            wizard.has_dir = bool(entries.filtered("is_dir"))

    def action_apply(self):
        self.ensure_one()
        entries = self.entry_ids
        if not entries:
            return {"type": "ir.actions.act_window_close"}
        if not self.recursive:
            for entry in entries.filtered("is_dir"):
                if entry.child_ids:
                    raise ValidationError(
                        _(
                            "Folder '%s' is not empty. Tick 'Delete folders "
                            "recursively' to delete it with all its content.",
                            entry.name,
                        )
                    )
        self.env["one.storage.operation"].start_delete(entries)
        return {"type": "ir.actions.act_window_close"}
