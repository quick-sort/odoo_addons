# Copyright 2026 One Storage
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

"""Default storage backend for One Storage.

A single global backend backs the root folder. It is resolved through the
``one_storage.default_backend_id`` system parameter so an administrator can
repoint the default from Settings without touching the database schema.
"""

from odoo import _, api, models


class StorageBackendDefault(models.Model):
    _inherit = "storage.backend"

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

        A backend's mirror root is the directory carrying ``backend_id = self``.
        Only directories (not the files under them) hold that key, so the search
        locates the unique root. Bind-mounting this backend elsewhere is done by
        pointing a directory's ``target_id`` at this root entry.

        Does not create a root automatically — an admin chooses where a backend
        is mirrored by creating a directory and setting its ``backend_id``. The
        default backend's root is provisioned by
        :meth:`one.storage.entry._get_or_create_root`.
        """
        self.ensure_one()
        return self.env["one.storage.entry"].search(
            [("backend_id", "=", self.id), ("entry_type", "=", "directory")],
            limit=1,
        )
