import hashlib
from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestStorageUpload(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.backend = cls.env.ref("storage_backend.default_storage_backend")
        cls.Upload = cls.env["storage.upload"]

    def _stage(self):
        path = self.Upload._stage_path("f.txt")
        return self.Upload.create({
            "name": "f.txt",
            "backend_id": self.backend.id,
            "relative_path": path,
        })

    def test_stage_path_under_mcp_staging(self):
        self.assertTrue(self.Upload._stage_path("f.txt").startswith(".mcp_staging/"))

    def test_commit_hash_relay(self):
        upload = self._stage()
        upload.write({"sha256": "abc", "size_bytes": 3})
        upload.commit()
        self.assertEqual(upload.state, "staged")
        self.assertEqual(upload.sha256, "abc")

    def test_commit_hash_presign(self):
        upload = self._stage()
        with self.backend.open(upload.relative_path, "wb") as f:
            f.write(b"hello")
        upload.commit()
        self.assertEqual(upload.state, "staged")
        self.assertEqual(upload.size_bytes, 5)
        self.assertEqual(upload.sha256, hashlib.sha256(b"hello").hexdigest())

    def test_consume_requires_staged_and_is_single_shot(self):
        upload = self._stage()
        with self.backend.open(upload.relative_path, "wb") as f:
            f.write(b"data")
        upload.commit()
        with upload.consume() as stream:
            self.assertEqual(stream.read(), b"data")
        self.assertEqual(upload.state, "consumed")
        with self.assertRaises(UserError):
            with upload.consume():
                pass

    def test_ownership_enforced(self):
        upload = self._stage()
        other_env = self.env(user=upload.create_uid.id + 1)
        with self.assertRaises(UserError):
            upload.with_env(other_env).commit()

    def test_expired_uploads_pruned_with_objects(self):
        upload = self._stage()
        with self.backend.open(upload.relative_path, "wb") as f:
            f.write(b"x")
        upload.write({
            "state": "staged",
            "expires_at": fields.Datetime.now() - timedelta(seconds=1),
        })
        self.Upload._cron_gc()
        self.assertEqual(upload.state, "expired")
        self.assertFalse(self.backend.file_exists(upload.relative_path))

    def test_expired_tokens_pruned(self):
        self.env["storage.mcp.token"]._issue(self.backend, "a.txt", "download")
        token = self.env["storage.mcp.token"].search([])
        token.expires_at = fields.Datetime.now() - timedelta(seconds=1)
        self.Upload._cron_gc()
        self.assertFalse(self.env["storage.mcp.token"].search([]))
