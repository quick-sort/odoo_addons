from odoo import fields, models


class StorageBackend(models.Model):
    _inherit = "storage.backend"

    mcp_read_enabled = fields.Boolean(
        string="MCP Read",
        default=False,
        help="Expose this backend's files to agents through the storage_* "
        "read tools and download URL signing.",
    )
    mcp_write_enabled = fields.Boolean(
        string="MCP Write",
        default=False,
        help="Allow agents to write into this backend through the storage_* "
        "write tools and upload URL signing.",
    )

    def presign_upload(self, relative_path, expires_in=600):
        """Return a native signed upload URL, or ``None`` to use the relay.

        The physical (gzip-mapped) key is what the adapter signs, so the URL
        writes the same key ``open()`` reads. Adapters without a
        ``presign_upload`` method return ``None``; a bridge
        (``storage_backend_s3_mcp``) provides it.
        """
        self.ensure_one()
        physical, _ = self._gzip_physical(relative_path)
        adapter = self._get_adapter()
        if not hasattr(adapter, "presign_upload"):
            return None
        return adapter.presign_upload(physical, expires_in=expires_in)

    def presign_download(self, relative_path, expires_in=600):
        """Return a native signed download URL, or ``None`` to use the relay."""
        self.ensure_one()
        physical, _ = self._gzip_physical(relative_path)
        adapter = self._get_adapter()
        if not hasattr(adapter, "presign_download"):
            return None
        return adapter.presign_download(physical, expires_in=expires_in)
