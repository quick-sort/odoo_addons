# Copyright 2026 One Storage
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

from odoo import _, fields, models


class OneStorageEntryMountWizard(models.TransientModel):
    """Choose a backend to graft onto a directory, then sync its content."""

    _name = "one.storage.entry.mount.wizard"
    _description = "One Storage Mount Wizard"

    entry_id = fields.Many2one(
        comodel_name="one.storage.entry",
        required=True,
        readonly=True,
        default=lambda self: self.env.context.get("default_entry_id"),
    )
    entry_name = fields.Char(related="entry_id.complete_name")
    backend_id = fields.Many2one(
        comodel_name="storage.backend",
        required=True,
    )
    backend_path = fields.Char(
        help="Optional root path inside the backend to mount."
    )

    def action_apply(self):
        """Create the mount point and enqueue an async recursive sync."""
        self.ensure_one()
        self.env["one.storage.mount"].create(
            {
                "name": self.backend_id.display_name,
                "entry_id": self.entry_id.id,
                "backend_id": self.backend_id.id,
                "backend_path": self.backend_path or "",
            }
        )
        self.entry_id.action_sync_from_backend()
        return {"type": "ir.actions.act_window_close"}
