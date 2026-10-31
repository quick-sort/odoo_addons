import hashlib
from urllib.parse import parse_qs, urlparse

from odoo.tests.common import HttpCase, tagged

from ..file_service import UPLOAD_SCOPE


@tagged("post_install", "-at_install")
class TestFileController(HttpCase):
    def _stage(self, name="file.bin"):
        return self.env["llm.mcp.file.tool"].attachment_stage_upload(name)

    def _put(self, url, data, headers=None):
        return self.opener.put(
            self.base_url() + url, data=data, headers=headers, timeout=10
        )

    def _replace_token(self, url, token):
        parsed = urlparse(url)
        return parsed.path + "?access_token=" + token

    def test_upload_commit_download_roundtrip(self):
        data = b"hello roundtrip"
        up = self._stage("rt.bin")
        r = self._put(up["upload"]["url"], data)
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["size"], len(data))
        self.assertEqual(r.json()["sha256"], hashlib.sha256(data).hexdigest())

        out = self.env["llm.mcp.file.tool"].attachment_commit_upload(up["attachment_id"])
        self.assertEqual(out["sha256"], hashlib.sha256(data).hexdigest())
        self.assertEqual(out["size"], len(data))

        down = self.env["llm.mcp.file.tool"].attachment_get_download_url(up["attachment_id"])
        r2 = self.opener.get(self.base_url() + down["download"]["url"], timeout=10)
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.content, data)

    def test_upload_url_is_single_use(self):
        up = self._stage("once.bin")
        self.assertEqual(self._put(up["upload"]["url"], b"first").status_code, 200)
        self.assertEqual(self._put(up["upload"]["url"], b"second").status_code, 409)

    def test_invalid_token_is_rejected(self):
        up = self._stage("bad.bin")
        parsed = urlparse(up["upload"]["url"])
        bad_url = parsed.path + "?" + parsed.query + "x"
        self.assertEqual(self._put(bad_url, b"data").status_code, 403)

    def test_token_is_bound_to_attachment(self):
        first = self._stage("a.bin")
        second = self._stage("b.bin")
        token = parse_qs(urlparse(first["upload"]["url"]).query)["access_token"][0]
        wrong_url = f"/mcp/files/{second['attachment_id']}?access_token={token}"
        self.assertEqual(self._put(wrong_url, b"data").status_code, 403)

    def test_expired_token_is_rejected(self):
        up = self._stage("expired.bin")
        attachment = self.env["ir.attachment"].browse(up["attachment_id"])
        token = self.env["llm.mcp.file.tool"]._sign(attachment, -10, UPLOAD_SCOPE)
        self.assertEqual(
            self._put(self._replace_token(up["upload"]["url"], token), b"data").status_code,
            403,
        )

    def test_multipart_is_refused_without_consuming_the_upload(self):
        data = b"multipart-payload"
        up = self._stage("multi.bin")
        url = up["upload"]["url"]
        r = self.opener.put(
            self.base_url() + url, files={"file": ("x.bin", data)}, timeout=10
        )
        self.assertEqual(r.status_code, 415)

        r2 = self._put(url, data, headers={"Content-Type": "application/octet-stream"})
        self.assertEqual(r2.status_code, 200)
        self.assertEqual(r2.json()["size"], len(data))

    def test_oversize_is_rejected(self):
        param = self.env["ir.config_parameter"].sudo()
        old = param.get_param("llm_mcp_server.max_file_upload_mb")
        param.set_param("llm_mcp_server.max_file_upload_mb", "0")
        try:
            up = self._stage("big.bin")
            r = self._put(up["upload"]["url"], b"0123456789")
            self.assertEqual(r.status_code, 413)
        finally:
            param.set_param(
                "llm_mcp_server.max_file_upload_mb", old or "64"
            )

    def test_zero_byte_file_roundtrip(self):
        up = self._stage("empty.bin")
        r = self._put(
            up["upload"]["url"], b"", headers={"Content-Type": "application/octet-stream"}
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["size"], 0)

        out = self.env["llm.mcp.file.tool"].attachment_commit_upload(up["attachment_id"])
        self.assertEqual(out["size"], 0)
        down = self.env["llm.mcp.file.tool"].attachment_get_download_url(up["attachment_id"])
        r2 = self.opener.get(self.base_url() + down["download"]["url"], timeout=10)
        self.assertEqual(r2.content, b"")

    def test_form_content_type_does_not_lose_the_body(self):
        data = b"form-encoded-but-binary\x00payload"
        up = self._stage("form.bin")
        r = self._put(
            up["upload"]["url"],
            data,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["sha256"], hashlib.sha256(data).hexdigest())

    def test_download_rejects_invalid_token(self):
        up = self._stage("down.bin")
        self.assertEqual(self._put(up["upload"]["url"], b"data").status_code, 200)
        self.env["llm.mcp.file.tool"].attachment_commit_upload(up["attachment_id"])
        url = (
            f"/web/content/ir.attachment/{up['attachment_id']}/raw"
            "?access_token=not-a-valid-token"
        )
        r = self.opener.get(self.base_url() + url, timeout=10)
        self.assertNotEqual(r.status_code, 200)
