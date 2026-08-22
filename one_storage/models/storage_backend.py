# Copyright 2026 One Storage
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

"""Default storage backend for One Storage.

A single global backend backs the root folder. It is resolved through the
``one_storage.default_backend_id`` system parameter so an administrator can
repoint the default from Settings without touching the database schema.
"""

from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class StorageBackendDefault(models.Model):
    _inherit = "storage.backend"

    entry_id = fields.Many2one(
        comodel_name="one.storage.entry",
        string="Mirror Root",
        ondelete="set null",
        index=True,
        copy=False,
        help="Root of the entry tree mirroring this backend's '/'. One per "
        "backend; mount points bind to it via their binding_id. The tree "
        "is persistent and filled lazily, one level per listing.",
    )

    @api.constrains("entry_id")
    def _check_entry_is_dir(self):
        for backend in self:
            if backend.entry_id and not backend.entry_id.is_dir:
                raise ValidationError(
                    _("The mirror root of a backend must be a directory.")
                )

    @classmethod
    def _default_param_key(cls):
        return "one_storage.default_backend_id"

    @api.model
    def _get_or_create_default(self):
        """Return the global default storage backend.

        Resolved from the ``one_storage.default_backend_id`` config parameter.
        When unset, a filesystem backend is provisioned and recorded in the
        parameter. Idempotent.
        """
        Icp = self.env["ir.config_parameter"].sudo()
        backend = self.browse(int(Icp.get_param(self._default_param_key()) or 0)).exists()
        if backend:
            return backend
        backend = self.create(
            {
                "name": _("One Storage Default"),
                "backend_type": "filesystem",
            }
        )
        Icp.set_param(self._default_param_key(), str(backend.id))
        return backend

    def _get_or_create_root_entry(self):
        """Return the ``one.storage.entry`` mirroring this backend's root ``/``.

        The mirror root is owned by the backend via ``entry_id``. Mounting a
        backend elsewhere is done by pointing a directory's ``binding_id``
        at this root entry.
        """
        self.ensure_one()
        return self.entry_id

    def action_open_files(self):
        """Open this backend's mirror root in the One Storage browser.

        Never syncs on open: freshness is provided by the Sync File Tree
        button or the per-folder Refresh action. A first open (empty mirror
        root) still seeds the first level so the browser isn't blank.
        """
        self.ensure_one()
        root = self.entry_id or self.env[
            "one.storage.entry"
        ]._get_or_create_mirror_root(self)
        if not root.child_ids:
            root._sync_children()
        return root.action_open_children()

    def action_sync_file_tree(self):
        """Enqueue a breadth-first full sync of the backend's mirror tree.

        One queue job per folder: the job syncs that folder's children (one
        backend listing) and enqueues a job per subdirectory, so the tree
        fills level by level without ever blocking on a recursive scan.
        Tracked as a single one.storage.operation record.
        """
        for backend in self:
            root = backend.entry_id or self.env[
                "one.storage.entry"
            ]._get_or_create_mirror_root(backend)
            self.env["one.storage.operation"].start_sync_tree(backend, root)
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Full sync scheduled"),
                "message": _(
                    "The file tree of %s will be refreshed in the "
                    "background, one folder per job.",
                ),
                "next": {"type": "ir.actions.act_window_close"},
            },
        }
