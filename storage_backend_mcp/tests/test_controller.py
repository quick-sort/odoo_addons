import hashlib

from odoo.tests.common import HttpCase, tagged


@tagged("post_install", "-at_install")
class TestStorageMcpController(HttpCase):
    def test_upload_download_roundtrip(self):
        backend = self.env.ref("storage_backend.default_storage_backend")
        backend.write({"mcp_read_enabled": True, "mcp_write_enabled": True})
        tool = self.env["storage.mcp.tool"]

        data = b"hello roundtrip"
        up = tool.storage_get_upload_url(backend.name, "rt.txt")
        r = self.opener.put(self.base_url() + up["upload"]["url"], data=data, timeout=10)
        self.assertEqual(r.status_code, 200)
        payload = r.json()
        self.assertEqual(payload["size"], len(data))
        self.assertEqual(payload["sha256"], hashlib.sha256(data).hexdigest())

        down = tool.storage_get_download_url(backend.name, "rt.txt")
        r2 = self.opener.get(self.base_url() + down["download"]["url"], timeout=10)
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.content, data)

    def test_oversize_aborted_and_cleaned(self):
        backend = self.env.ref("storage_backend.default_storage_backend")
        backend.write({"mcp_write_enabled": True})
        tool = self.env["storage.mcp.tool"]
        up = tool.storage_get_upload_url(backend.name, "big.txt")
        self.env["storage.mcp.token"].search([]).write({"max_size_bytes": 5})
        r = self.opener.put(
            self.base_url() + up["upload"]["url"], data=b"0123456789", timeout=10
        )
        self.assertEqual(r.status_code, 413)
        self.assertFalse(backend.file_exists("big.txt"))
