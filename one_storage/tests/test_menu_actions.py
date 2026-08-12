# Copyright 2026 One Storage
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

import base64

from odoo.tests import HttpCase

from .common import OneStorageCommon


class TestUploadDeleteWizards(OneStorageCommon):
    def setUp(self):
        super().setUp()
        self.file_entry = self.env["one.storage.entry"].create(
            {
                "name": "doc.txt",
                "entry_type": "file",
                "parent_id": self.root_folder.id,
            }
        )
        self.file_entry.set_content(base64.b64encode(b"old"), binary=False)

    def test_upload_wizard_overwrites_content(self):
        wizard = (
            self.env["one.storage.entry.upload.wizard"]
            .with_context(default_entry_id=self.file_entry.id)
            .create({"datas": base64.b64encode(b"new content"), "filename": "doc.txt"})
        )
        wizard.action_apply()
        self.assertEqual(self.file_entry.file_size, len(b"new content"))
        self.assertEqual(self.backend.get("doc.txt"), b"new content")
        self.assertEqual(self.file_entry.state, "synced")

    def test_upload_wizard_rejects_directory(self):
        wizard = (
            self.env["one.storage.entry.upload.wizard"]
            .with_context(default_entry_id=self.root_folder.id)
            .create({"datas": base64.b64encode(b"x"), "filename": "x"})
        )
        with self.assertRaises(Exception):
            wizard.action_apply()

    def test_delete_wizard_unlinks_entry(self):
        entry_id = self.file_entry.id
        wizard = (
            self.env["one.storage.entry.delete.wizard"]
            .with_context(default_entry_id=entry_id)
            .create({})
        )
        wizard.action_apply()
        self.assertFalse(self.env["one.storage.entry"].browse(entry_id).exists())

    def test_action_edit_returns_form_action(self):
        res = self.file_entry.action_edit()
        self.assertEqual(res["res_model"], "one.storage.entry")
        self.assertEqual(res["res_id"], self.file_entry.id)
        self.assertEqual(res["view_mode"], "form")


class TestPreviewRoute(HttpCase):
    def test_preview_route_serves_inline(self):
        # Clear any seeded root so the single-root constraint holds.
        self.env["one.storage.entry"].search([("parent_id", "=", False)]).unlink()
        tmp_name = "one_storage_preview_test_%s" % self.env.cr.dbname
        backend = self.env["storage.backend"].create(
            {"name": "Preview FS", "backend_type": "filesystem", "directory_path": tmp_name}
        )
        root = self.env["one.storage.entry"].create(
            {"name": "root", "entry_type": "directory", "backend_id": backend.id}
        )
        file_entry = self.env["one.storage.entry"].create(
            {"name": "note.txt", "entry_type": "file", "parent_id": root.id}
        )
        file_entry.set_content(base64.b64encode(b"hello"), binary=False)
        res = self.url_open("/one_storage/entry/%s/preview" % file_entry.id, timeout=12)
        self.assertEqual(res.status_code, 200)
        self.assertIn("inline", res.headers.get("Content-Disposition", ""))
        self.assertEqual(res.content, b"hello")
