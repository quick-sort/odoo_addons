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
                "directory_path": "one_storage",
            }
        )
        Icp.set_param(self._default_param_key(), str(backend.id))
        return backend
