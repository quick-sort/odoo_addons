import hashlib
import os
import uuid
from contextlib import contextmanager
from datetime import timedelta

from odoo import api, fields, models
from odoo.exceptions import UserError

STAGING_PREFIX = ".mcp_staging"
UPLOAD_TTL_HOURS = 24


class StorageUpload(models.Model):
    _name = "storage.upload"
    _description = "Storage Upload (staged)"
    _order = "id desc"

    name = fields.Char(required=True)
    backend_id = fields.Many2one(
        "storage.backend", required=True, ondelete="cascade", index=True
    )
    relative_path = fields.Char(required=True)
    sha256 = fields.Char()
    size_bytes = fields.Integer()
    state = fields.Selection(
        [
            ("pending", "Pending"),
            ("staged", "Staged"),
            ("consumed", "Consumed"),
            ("expired", "Expired"),
        ],
        default="pending",
        required=True,
        index=True,
    )
    expires_at = fields.Datetime(index=True)
    consumed_model = fields.Char()
    consumed_res_id = fields.Integer()

    @api.model
    def _stage_path(self, filename):
        """The staging path is always generated here — agents never invent it."""
        name = os.path.basename(filename or "upload")
        return f"{STAGING_PREFIX}/{uuid.uuid4().hex}/{name}"

    def _check_owner(self):
        self.ensure_one()
        if self.create_uid.id != self.env.uid and not self.env.su:
            raise UserError("You cannot operate on an upload you did not create.")

    def commit(self):
        """Confirm a staged upload: fill in integrity if the relay hasn't, mark staged."""
        self.ensure_one()
        self._check_owner()
        if self.state != "pending":
            raise UserError("Only pending uploads can be committed.")
        if not self.sha256:
            self.sha256, self.size_bytes = self._hash_from_backend()
        self.write({
            "state": "staged",
            "expires_at": fields.Datetime.now() + timedelta(hours=UPLOAD_TTL_HOURS),
        })

    def _hash_from_backend(self):
        """Stream the object and compute its sha256 and byte size (no full read)."""
        digest = hashlib.sha256()
        size = 0
        with self.backend_id.open(self.relative_path, "rb") as stream:
            while True:
                chunk = stream.read(1024 * 1024)
                if not chunk:
                    break
                digest.update(chunk)
                size += len(chunk)
        return digest.hexdigest(), size

    @contextmanager
    def consume(self, res_model=None, res_id=None):
        """Yield a readable stream of the staged object, then mark it consumed.

        Single-shot: the object is deleted on exit and the state becomes
        ``consumed``, so a downstream tool cannot replay the same ``file_id``.
        """
        self.ensure_one()
        self._check_owner()
        if self.state != "staged":
            raise UserError("Only staged uploads can be consumed.")
        if self.expires_at and self.expires_at <= fields.Datetime.now():
            raise UserError("This upload has expired.")
        with self.backend_id.open(self.relative_path, "rb") as stream:
            yield stream
        self.write({
            "state": "consumed",
            "consumed_model": res_model or False,
            "consumed_res_id": res_id or 0,
        })
        self.backend_id.delete(self.relative_path)

    @api.model
    def _cron_gc(self):
        """Prune expired capability tokens and unconsumed staged uploads."""
        self.env["storage.mcp.token"].search(
            [("expires_at", "<=", fields.Datetime.now())]
        ).unlink()
        expired = self.search([
            ("expires_at", "<=", fields.Datetime.now()),
            ("state", "in", ["pending", "staged"]),
        ])
        for upload in expired:
            upload.backend_id.delete(upload.relative_path)
            upload.state = "expired"
