# Copyright 2026 One Storage
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class OneStorageEntryMountWizard(models.TransientModel):
    """Mount a storage backend on a folder (or unmount it).

    Mounting binds the folder to the backend's persistent mirror root (see
    ``one.storage.entry._get_or_create_mirror_root``): the folder aliases the
    mirror tree, which is filled lazily one level per listing. Unmounting
    only drops the binding — the mirror tree (and the backend's bytes) stay,
    so remounting is instant.
    """

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
        string="Storage Backend",
        required=True,
    )
    read_only = fields.Boolean(
        default=False,
        help="Mount the mirror read-only: writes, deletes and creation "
        "under it are rejected.",
    )
    is_mounted = fields.Boolean(
        compute="_compute_is_mounted",
        help="True when the folder is bound to a mirror (unmount mode).",
    )
    mounted_backend_id = fields.Many2one(
        comodel_name="storage.backend",
        compute="_compute_is_mounted",
    )

    @api.depends("entry_id")
    def _compute_is_mounted(self):
        for wizard in self:
            entry = wizard.entry_id
            if not entry:
                wizard.is_mounted = False
                wizard.mounted_backend_id = False
                continue
            entry = entry._follow()
            mirror_backend = entry.binding_id.backend_id or entry.backend_id
            wizard.is_mounted = bool(mirror_backend)
            wizard.mounted_backend_id = mirror_backend

    def action_mount(self):
        self.ensure_one()
        entry = self.entry_id
        if not entry.is_dir:
            raise ValidationError(_("Only folders can mount a storage backend."))
        if entry.binding_id:
            raise ValidationError(
                _(
                    "Folder '%s' is already bound to '%s'.",
                    entry.name,
                    entry.binding_id.complete_name,
                )
            )
        mirror = self.env["one.storage.entry"]._get_or_create_mirror_root(
            self.backend_id
        )
        entry.write({"binding_id": mirror.id})
        if self.read_only:
            mirror.sudo().write({"read_only": True})
        return {"type": "ir.actions.act_window_close"}

    def action_unmount(self):
        self.ensure_one()
        entry = self.entry_id
        if not entry.binding_id:
            raise ValidationError(
                _("Folder '%s' has no mounted backend.", entry.name)
            )
        # Drop only the binding; the mirror tree and backend bytes stay.
        entry.write({"binding_id": False})
        return {"type": "ir.actions.act_window_close"}
