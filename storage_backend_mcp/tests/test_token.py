from datetime import timedelta

from odoo import fields
from odoo.exceptions import AccessError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestStorageMcpToken(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.backend = cls.env.ref("storage_backend.default_storage_backend")
        cls.Token = cls.env["storage.mcp.token"]

    def test_token_lookup_by_hash(self):
        raw = self.Token._issue(self.backend, "a.txt", "download")
        token = self.Token._find_by_raw(raw)
        self.assertTrue(token)
        self.assertEqual(token.relative_path, "a.txt")

    def test_expired_token_rejected(self):
        raw = self.Token._issue(self.backend, "a.txt", "download")
        token = self.Token._find_by_raw(raw)
        token.expires_at = fields.Datetime.now() - timedelta(seconds=1)
        self.assertFalse(self.Token._find_by_raw(raw))

    def test_upload_token_single_use(self):
        raw = self.Token._issue(self.backend, "a.txt", "upload")
        token = self.Token._find_by_raw(raw)
        self.assertTrue(token._use_once())
        self.assertFalse(token._use_once())

    def test_token_rejects_path_escape(self):
        with self.assertRaises(AccessError):
            self.Token._issue(self.backend, "../etc/passwd", "upload")
        with self.assertRaises(AccessError):
            self.Token._issue(self.backend, "/abs/path", "upload")
