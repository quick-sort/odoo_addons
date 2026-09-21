from typing import Any

from odoo import models
from odoo.exceptions import UserError

from odoo.addons.llm.decorators import llm_tool

MAX_DIRECT_READ = 256 * 1024  # small text files are returned inline up to this size


class StorageMcpTool(models.AbstractModel):
    _name = "storage.mcp.tool"
    _description = "Storage MCP tools"

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def _resolve_backend(self, name):
        backend = self.env["storage.backend"].search([("name", "=", name)], limit=1)
        if not backend:
            raise UserError(f"Storage backend '{name}' not found.")
        return backend

    def _require_read(self, backend):
        if not backend.mcp_read_enabled:
            raise UserError("MCP read is disabled on this backend.")

    def _require_write(self, backend):
        if not backend.mcp_write_enabled:
            raise UserError("MCP write is disabled on this backend.")

    def _max_relay_size(self):
        mb = int(self.env["ir.config_parameter"].sudo().get_param(
            "storage_backend_mcp.max_relay_size_mb", "2047"))
        return mb * 1024 * 1024

    @staticmethod
    def _curl(method, url):
        if method == "PUT":
            return f"curl -T <file> '{url}'"
        return f"curl '{url}'"

    def _presign_spec(self, presigned, default_method):
        spec = dict(presigned)
        spec.setdefault("method", default_method)
        spec.setdefault("headers", {})
        return spec

    def _upload_spec(self, backend, path, overwrite=False, expires_in=600, upload_id=None):
        self._require_write(backend)
        if not overwrite and backend.file_exists(path):
            raise UserError(
                f"'{path}' already exists on this backend; pass overwrite=True to replace it.")
        presigned = backend.presign_upload(path, expires_in=expires_in)
        if presigned:
            return self._presign_spec(presigned, "PUT")
        raw = self.env["storage.mcp.token"]._issue(
            backend, path, "upload", expires_in=expires_in,
            max_size_bytes=self._max_relay_size(), upload_id=upload_id,
        )
        return {"url": f"/storage_mcp/t/{raw}", "method": "PUT", "headers": {}}

    def _download_spec(self, backend, path, expires_in=600):
        self._require_read(backend)
        presigned = backend.presign_download(path, expires_in=expires_in)
        if presigned:
            return self._presign_spec(presigned, "GET")
        raw = self.env["storage.mcp.token"]._issue(
            backend, path, "download", expires_in=expires_in)
        return {"url": f"/storage_mcp/t/{raw}", "method": "GET", "headers": {}}

    # ------------------------------------------------------------------
    # Read tools
    # ------------------------------------------------------------------

    @llm_tool(read_only_hint=True, destructive_hint=False)
    def storage_list_backends(self) -> list[dict[str, Any]]:
        """List storage backends available to agents, with their MCP read/write flags."""
        backends = self.env["storage.backend"].search([])
        return [{
            "name": b.name,
            "backend_type": b.backend_type,
            "mcp_read_enabled": b.mcp_read_enabled,
            "mcp_write_enabled": b.mcp_write_enabled,
        } for b in backends]

    @llm_tool(read_only_hint=True, destructive_hint=False)
    def storage_list_files(self, backend: str, path: str = "") -> dict[str, Any]:
        """List files under a path on a storage backend. Returns names, sizes and
        directory flags. ``path`` is a backend-relative POSIX path ('' for root)."""
        b = self._resolve_backend(backend)
        self._require_read(b)
        items = b.list_files(path, detail=True)
        return {"entries": items}

    @llm_tool(read_only_hint=True, destructive_hint=False)
    def storage_stat_file(self, backend: str, path: str) -> dict[str, Any]:
        """Return metadata (size, is_dir, mtime) for a file on a storage backend."""
        b = self._resolve_backend(backend)
        self._require_read(b)
        return b.stat(path)

    @llm_tool(read_only_hint=True, destructive_hint=False)
    def storage_read_file(self, backend: str, path: str) -> dict[str, Any]:
        """Read a small text file from a storage backend and return its content
        inline. Larger files are not returned inline; use storage_get_download_url
        and fetch it with curl instead."""
        b = self._resolve_backend(backend)
        self._require_read(b)
        size = b.get_size(path)
        if size > MAX_DIRECT_READ:
            return {
                "size": size,
                "truncated": True,
                "message": "File too large to inline; use storage_get_download_url.",
            }
        with b.open(path, "rb") as stream:
            data = stream.read()
        return {"size": size, "content": data.decode("utf-8", errors="replace")}

    @llm_tool(read_only_hint=True, destructive_hint=False)
    def storage_get_download_url(self, backend: str, path: str) -> dict[str, Any]:
        """Return a temporary URL to download a file from a storage backend. Fetch
        it with curl; the bytes do not travel through the MCP channel."""
        b = self._resolve_backend(backend)
        spec = self._download_spec(b, path)
        return {"download": spec, "curl": self._curl(spec["method"], spec["url"])}

    # ------------------------------------------------------------------
    # Write tools
    # ------------------------------------------------------------------

    @llm_tool(destructive_hint=False)
    def storage_get_upload_url(
        self, backend: str, path: str, overwrite: bool = False
    ) -> dict[str, Any]:
        """Return a temporary URL to upload a file to a storage backend. Upload it
        with curl; the bytes do not travel through the MCP channel. ``overwrite``
        must be True to replace an existing file."""
        b = self._resolve_backend(backend)
        spec = self._upload_spec(b, path, overwrite=overwrite)
        return {"upload": spec, "curl": self._curl(spec["method"], spec["url"])}

    @llm_tool(destructive_hint=False)
    def storage_stage_upload(self, backend: str, filename: str) -> dict[str, Any]:
        """Stage an upload so a downstream tool can consume it by ``file_id``.
        Returns a file_id plus a temporary upload URL; after uploading with curl,
        call storage_commit_upload(file_id)."""
        b = self._resolve_backend(backend)
        self._require_write(b)
        path = self.env["storage.upload"]._stage_path(filename)
        upload = self.env["storage.upload"].create({
            "name": filename,
            "backend_id": b.id,
            "relative_path": path,
        })
        spec = self._upload_spec(b, path, expires_in=3600, upload_id=upload.id)
        return {
            "file_id": upload.id,
            "upload": spec,
            "curl": self._curl(spec["method"], spec["url"]),
        }

    @llm_tool(destructive_hint=False)
    def storage_commit_upload(self, file_id: int) -> dict[str, Any]:
        """Confirm a staged upload by ``file_id`` after uploading its bytes.
        Returns the computed sha256 and size once the object is verified."""
        upload = self.env["storage.upload"].browse(file_id)
        if not upload.exists():
            raise UserError(f"Upload {file_id} not found.")
        upload.commit()
        return {
            "file_id": upload.id,
            "state": upload.state,
            "sha256": upload.sha256,
            "size": upload.size_bytes,
        }

    @llm_tool(destructive_hint=True)
    def storage_delete_file(self, backend: str, path: str) -> dict[str, Any]:
        """Delete a file from a storage backend. Destructive and irreversible."""
        b = self._resolve_backend(backend)
        self._require_write(b)
        b.delete(path)
        return {"deleted": path}
