from datetime import timedelta

from odoo import fields
from odoo.exceptions import UserError
from odoo.tests.common import TransactionCase, tagged


@tagged("post_install", "-at_install")
class TestFileUploadLifecycle(TransactionCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.Upload = cls.env["llm.mcp.file.upload"]

    def _user(self, login):
        return self.env["res.users"].create({
            "name": login,
            "login": login,
            "group_ids": [(6, 0, [self.env.ref("base.group_user").id])],
        })

    def _upload_row(self, name, state="pending", expires=None, attachment=None):
        attachment = attachment or self.env["ir.attachment"].create({"name": name})
        return self.Upload.create({
            "name": name,
            "attachment_id": attachment.id,
            "state": state,
            "expires_at": expires or fields.Datetime.now() + timedelta(hours=24),
        })

    def test_claim_is_atomic_single_use(self):
        upload = self._upload_row("claim.bin")
        self.assertTrue(upload._claim_upload())
        self.assertFalse(upload._claim_upload())
        self.assertEqual(upload.state, "uploaded")

    def test_owner_check(self):
        owner = self._user("file_lifecycle_owner")
        outsider = self._user("file_lifecycle_outsider")
        attachment = self.env["ir.attachment"].create({"name": "owner.bin"})
        upload = self.Upload.with_user(owner).create({
            "name": "owner.bin",
            "attachment_id": attachment.id,
            "expires_at": fields.Datetime.now() + timedelta(hours=24),
        })
        upload._check_owner()
        with self.assertRaises(UserError):
            upload.with_user(outsider)._check_owner()

    def test_cron_cleans_uncommitted_attachments_only(self):
        expired = fields.Datetime.now() - timedelta(hours=1)
        pending_attachment = self.env["ir.attachment"].create({"name": "pending.bin"})
        committed_attachment = self.env["ir.attachment"].create({"name": "kept.bin"})
        pending = self._upload_row(
            "pending.bin", state="uploaded", expires=expired,
            attachment=pending_attachment,
        )
        committed = self._upload_row(
            "kept.bin", state="committed", expires=expired,
            attachment=committed_attachment,
        )

        self.Upload._cron_gc()

        self.assertEqual(pending.state, "expired")
        self.assertFalse(pending_attachment.exists())
        self.assertTrue(committed_attachment.exists())
        self.assertTrue(committed.exists())
