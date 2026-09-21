import hashlib
import secrets
from datetime import timedelta

from odoo import api, fields, models

TOKEN_TTL_DEFAULT = 600
TOKEN_TTL_MAX = 3600


class StorageMcpToken(models.Model):
    _name = "storage.mcp.token"
    _description = "Storage MCP Capability Token"
    _order = "expires_at, id"

    token_hash = fields.Char(required=True, index=True)
    backend_id = fields.Many2one(
        "storage.backend", required=True, ondelete="cascade", index=True
    )
    relative_path = fields.Char(required=True)
    mode = fields.Selection(
        [("upload", "Upload"), ("download", "Download")], required=True
    )
    expires_at = fields.Datetime(required=True, index=True)
    max_size_bytes = fields.Integer()
    uses_used = fields.Integer(default=0)
    upload_id = fields.Many2one(
        "storage.upload", ondelete="cascade", index=True,
        help="The staged upload this token transfers, when issued by "
        "storage_stage_upload.",
    )

    @api.model
    def _issue(self, backend, relative_path, mode, expires_in=TOKEN_TTL_DEFAULT,
               max_size_bytes=None, upload_id=None):
        """Create a capability token and return its raw (secret) value.

        Only the sha256 lands in the DB; the raw token appears solely in the
        URL handed to the agent. The path is validated here so the controller
        never accepts a path from the request.
        """
        backend._get_adapter()._check_relative_path(relative_path)
        expires_in = min(expires_in or TOKEN_TTL_DEFAULT, TOKEN_TTL_MAX)
        raw = secrets.token_urlsafe(32)
        self.create({
            "token_hash": hashlib.sha256(raw.encode()).hexdigest(),
            "backend_id": backend.id,
            "relative_path": relative_path,
            "mode": mode,
            "expires_at": fields.Datetime.now() + timedelta(seconds=expires_in),
            "max_size_bytes": max_size_bytes,
            "upload_id": upload_id,
        })
        return raw

    def _find_by_raw(self, raw):
        """Return the live token matching ``raw``, or an empty recordset."""
        if not raw:
            return self.env["storage.mcp.token"]
        token_hash = hashlib.sha256(raw.encode()).hexdigest()
        token = self.search([("token_hash", "=", token_hash)], limit=1)
        if not token or token.expires_at <= fields.Datetime.now():
            return self.env["storage.mcp.token"]
        return token

    def _use_once(self):
        """Mark a one-shot token used; return False on a replay."""
        if self.mode == "upload" and self.uses_used:
            return False
        self.uses_used += 1
        return True
