# Copyright 2026 One Storage
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

from odoo import fields, models


class OneStorageMount(models.Model):
    """A mount point binds a storage backend to a folder subtree.

    Files created below the mounted folder (or any descendant folder) are
    routed to the mount's backend instead of the folder's own backend,
    mirroring Linux's ``mount`` semantics: different backends can be grafted
    onto a single folder tree.
    """

    _name = "one.storage.mount"
    _description = "One Storage Mount Point"
    _order = "name"

    name = fields.Char(required=True)
    entry_id = fields.Many2one(
        comodel_name="one.storage.entry",
        required=True,
        ondelete="cascade",
    )
    backend_id = fields.Many2one(
        comodel_name="storage.backend",
        required=True,
        ondelete="restrict",
    )
    backend_path = fields.Char(
        help="Root path inside the backend for this mount."
    )
    active = fields.Boolean(default=True)
