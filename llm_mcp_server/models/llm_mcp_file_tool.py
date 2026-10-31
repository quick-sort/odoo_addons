import hashlib
import os
import time
from datetime import timedelta
from typing import Any

from odoo import fields, models
from odoo.exceptions import UserError
from odoo.tools.misc import limited_field_access_token

from odoo.addons.llm.decorators import llm_tool

from ..file_service import (
    DEFAULT_MAX_UPLOAD_MB,
    DOWNLOAD_SCOPE,
    DOWNLOAD_TOKEN_TTL,
    UPLOAD_SCOPE,
    UPLOAD_TOKEN_TTL,
    UPLOAD_TTL_HOURS,
)


class LLMMCPFileTool(models.AbstractModel):
    _name = "llm.mcp.file.tool"
    _description = "MCP file tools"

    def _max_upload_bytes(self):
        mb = int(self.env["ir.config_parameter"].sudo().get_param(
            "llm_mcp_server.max_file_upload_mb", DEFAULT_MAX_UPLOAD_MB))
        return mb * 1024 * 1024

    @staticmethod
    def _sign(attachment, ttl, scope):
        timestamp = hex(int(time.time()) + ttl)
        return limited_field_access_token(
            attachment.sudo(), "raw", timestamp=timestamp, scope=scope)

    def _upload_url(self, attachment):
        token = self._sign(attachment, UPLOAD_TOKEN_TTL, UPLOAD_SCOPE)
        return f"/mcp/files/{attachment.id}?access_token={token}"

    def _download_url(self, attachment):
        token = self._sign(attachment, DOWNLOAD_TOKEN_TTL, DOWNLOAD_SCOPE)
        return (
            f"/web/content/ir.attachment/{attachment.id}/raw"
            f"?access_token={token}&download=true"
        )

    @staticmethod
    def _curl(method, url):
        if method == "PUT":
            return f"curl -T <file> '{url}'"
        return f"curl -L -o <file> '{url}'"

    @llm_tool(destructive_hint=False, groups=("base.group_user",))
    def attachment_stage_upload(self, filename: str) -> dict[str, Any]:
        """Start a file upload and return an ``attachment_id`` plus a temporary upload
        URL. Upload the bytes with the returned curl command, then call
        attachment_commit_upload(attachment_id). The ``attachment_id`` is an ir.attachment id;
        bytes never travel through the MCP channel."""
        name = os.path.basename(filename or "upload") or "upload"
        attachment = self.env["ir.attachment"].create({"name": name})
        self.env["llm.mcp.file.upload"].create({
            "name": name,
            "attachment_id": attachment.id,
            "expires_at": fields.Datetime.now() + timedelta(hours=UPLOAD_TTL_HOURS),
        })
        url = self._upload_url(attachment)
        spec = {"url": url, "method": "PUT", "headers": {}}
        return {
            "attachment_id": attachment.id,
            "upload": spec,
            "curl": self._curl("PUT", url),
        }

    @llm_tool(destructive_hint=False, groups=("base.group_user",))
    def attachment_commit_upload(
        self, attachment_id: int, res_model: str = "", res_id: int = 0
    ) -> dict[str, Any]:
        """Confirm an uploaded file by ``attachment_id``. Optionally bind it to one
        business record by passing both ``res_model`` and ``res_id``; access to
        the file then follows that record's ACL. Returns sha256 and size."""
        attachment = self.env["ir.attachment"].browse(attachment_id).exists()
        if not attachment:
            raise UserError(f"File {attachment_id} not found.")
        upload = self.env["llm.mcp.file.upload"].search([
            ("attachment_id", "=", attachment.id),
        ], order="id desc", limit=1)
        if not upload:
            raise UserError(f"File {attachment_id} is not a staged upload.")
        upload._check_owner()
        if upload.state == "pending":
            raise UserError("No bytes uploaded yet; upload the file before committing.")
        if upload.state != "uploaded":
            raise UserError(f"Upload is {upload.state}; it cannot be committed.")

        if bool(res_model) != bool(res_id):
            raise UserError("res_model and res_id must be provided together.")
        if res_model:
            if res_model not in self.env:
                raise UserError(f"Unknown model '{res_model}'.")
            if not self.env[res_model].browse(res_id).exists():
                raise UserError(f"{res_model} record {res_id} not found.")
            # Runs as the caller: core checks write access to the target record.
            attachment.write({"res_model": res_model, "res_id": res_id})

        if not upload.sha256:
            data = attachment.raw or b""
            upload.sha256 = hashlib.sha256(data).hexdigest()
        upload.write({
            "state": "committed",
            "size_bytes": attachment.file_size,
            "committed_model": res_model,
            "committed_res_id": res_id,
        })
        return {
            "attachment_id": attachment.id,
            "state": upload.state,
            "sha256": upload.sha256,
            "size": upload.size_bytes,
            "res_model": upload.committed_model,
            "res_id": upload.committed_res_id,
        }

    @llm_tool(
        read_only_hint=True,
        destructive_hint=False,
        groups=("base.group_user",),
    )
    def attachment_get_download_url(self, attachment_id: int) -> dict[str, Any]:
        """Return a short-lived URL to download the file identified by
        ``attachment_id``. Fetch it with curl; the bytes do not travel through the
        MCP channel. Access is checked as the calling user."""
        attachment = self.env["ir.attachment"].browse(attachment_id).exists()
        if not attachment:
            raise UserError(f"File {attachment_id} not found.")
        attachment.check_access("read")
        url = self._download_url(attachment)
        return {
            "download": {"url": url, "method": "GET", "headers": {}},
            "curl": self._curl("GET", url),
        }
