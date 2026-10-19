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

    def test_form_content_type_does_not_lose_the_body(self):
        """A client that lets curl pick the default content type still uploads.

        ``curl --data-binary @file`` sends
        ``application/x-www-form-urlencoded``, and Odoo parses form bodies into
        ``request.form`` before the controller runs. Werkzeug's form parser
        consumes the stream without caching it, so the controller's
        ``get_data()`` sees ``b""`` -- and the relay happily stores an empty
        file and reports success.
        """
        backend = self.env.ref("storage_backend.default_storage_backend")
        backend.write({"mcp_read_enabled": True, "mcp_write_enabled": True})
        tool = self.env["storage.mcp.tool"]

        data = b"form-encoded-but-binary\x00payload"
        up = tool.storage_get_upload_url(backend.name, "form.txt")
        r = self.opener.put(
            self.base_url() + up["upload"]["url"],
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
            timeout=10,
        )
        self.assertEqual(r.status_code, 200)
        payload = r.json()
        self.assertEqual(payload["size"], len(data))
        self.assertEqual(payload["sha256"], hashlib.sha256(data).hexdigest())

    def test_multipart_upload_is_refused_without_spending_the_token(self):
        """A multipart body is an envelope, not the file; refuse it loudly.

        Storing the envelope would hand the consumer a corrupted blob, and
        extracting "the file" is ambiguous. The refusal must not burn the
        one-shot token, so the caller can retry the same URL with the raw-body
        form the tool's curl hint uses.
        """
        backend = self.env.ref("storage_backend.default_storage_backend")
        backend.write({"mcp_read_enabled": True, "mcp_write_enabled": True})
        tool = self.env["storage.mcp.tool"]

        data = b"multipart-payload"
        up = tool.storage_get_upload_url(backend.name, "multi.txt")
        url = self.base_url() + up["upload"]["url"]
        r = self.opener.put(url, files={"file": ("x.bin", data)}, timeout=10)
        self.assertEqual(r.status_code, 415)
        self.assertFalse(backend.file_exists("multi.txt"))

        r2 = self.opener.put(
            url,
            data=data,
            headers={"Content-Type": "application/octet-stream"},
            timeout=10,
        )
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.json()["size"], len(data))

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

    def test_large_body_roundtrip_and_hash(self):
        backend = self.env.ref("storage_backend.default_storage_backend")
        backend.write({"mcp_read_enabled": True, "mcp_write_enabled": True})
        tool = self.env["storage.mcp.tool"]

        # > 2 MiB, larger than any single-write chunk the relay might use.
        data = (b"0123456789abcdef" * 131072) + b"tail"
        up = tool.storage_get_upload_url(backend.name, "large.bin")
        r = self.opener.put(self.base_url() + up["upload"]["url"], data=data, timeout=30)
        self.assertEqual(r.status_code, 200)
        payload = r.json()
        self.assertEqual(payload["size"], len(data))
        self.assertEqual(payload["sha256"], hashlib.sha256(data).hexdigest())

        down = tool.storage_get_download_url(backend.name, "large.bin")
        r2 = self.opener.get(self.base_url() + down["download"]["url"], timeout=30)
        self.assertEqual(r2.content, data)
