import base64

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError


class DataChunk(models.Model):
    _inherit = "dataset.data_chunk"

    raw_data = fields.Binary(
        compute="_compute_raw_data", inverse="_inverse_raw_data", attachment=False
    )

    def _storage_backend(self, required=True):
        """Return only the configured backend with service-level privileges."""
        self.ensure_one()
        backend = self.dataset_id.sudo().storage_id
        if not backend or not self.key:
            if not required:
                return self.env["storage.backend"]
            if not backend:
                raise UserError(_("No storage backend is configured for this chunk."))
            raise UserError(_("The chunk has no storage key."))
        return backend.sudo().with_context(storage_backend_force_relative_path=True)

    def _read_payload(self):
        self.ensure_one()
        self.check_access("read")
        backend = self._storage_backend()
        if not backend.file_exists(self.key):
            return b""
        with backend.open(self.key, "rb") as stream:
            return stream.read()

    def _compute_raw_data(self):
        for record in self:
            record.check_access("read")
            backend = record._storage_backend(required=False)
            if not backend or not backend.file_exists(record.key):
                record.raw_data = False
                continue
            with backend.open(record.key, "rb") as stream:
                record.raw_data = base64.b64encode(stream.read())

    def _inverse_raw_data(self):
        for record in self:
            record.check_access("write")
            backend = record._storage_backend()
            if record.raw_data is not False and record.raw_data is not None:
                encoded = (
                    record.raw_data.encode("ascii")
                    if isinstance(record.raw_data, str)
                    else record.raw_data
                )
                payload = base64.b64decode(encoded)
                with backend.open(record.key, "wb") as stream:
                    stream.write(payload)
                record.write(
                    {"size": backend.get_size(record.key), "state": "exists"}
                )
            else:
                if backend.file_exists(record.key):
                    backend.delete(record.key)
                record.write({"size": 0, "state": "missing"})

    def raw_data_exist(self):
        self.ensure_one()
        self.check_access("read")
        backend = self._storage_backend(required=False)
        return bool(backend and backend.file_exists(self.key))

    def cleanup_raw_data(self):
        self.check_access("write")
        for record in self:
            backend = record._storage_backend()
            if backend.file_exists(record.key):
                backend.delete(record.key)
            record.write({"size": 0, "state": "missing"})

    @api.ondelete(at_uninstall=False)
    def _unlink_except_stored_payload(self):
        self.check_access("unlink")
        for record in self:
            if record.raw_data_exist():
                raise ValidationError(
                    _(
                        "Stored payload exists for chunk %(key)s. Use Delete Stored "
                        "Payload before deleting the catalog row."
                    )
                    % {"key": record.key}
                )
