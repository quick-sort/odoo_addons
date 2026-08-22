# Copyright 2026 One Storage
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

import base64

from odoo.addons.queue_job.tests.common import trap_jobs
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
        with self.backend.open("doc.txt", "rb") as stream:
            self.assertEqual(stream.read(), b"new content")
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
            .with_context(default_entry_ids=[(6, 0, [entry_id])])
            .create({})
        )
        with trap_jobs() as trap:
            wizard.action_apply()
            trap.perform_enqueued_jobs()
        self.assertFalse(self.env["one.storage.entry"].browse(entry_id).exists())


class TestPreviewRoute(HttpCase):
    def _setup_file(self, payload=b"hello"):
        self.authenticate("admin", "admin")
        # Clear any seeded root so the single-root constraint holds.
        self.env["one.storage.entry"].search([("parent_id", "=", False)]).unlink()
        tmp_name = "one_storage_preview_test_%s" % self.env.cr.dbname
        backend = self.env["storage.backend"].create(
            {"name": "Preview FS", "backend_type": "filesystem", "directory_path": tmp_name}
        )
        root = self.env["one.storage.entry"].create(
            {"name": "root", "entry_type": "directory"}
        )
        backend.entry_id = root
        file_entry = self.env["one.storage.entry"].create(
            {"name": "note.txt", "entry_type": "file", "parent_id": root.id}
        )
        file_entry.set_content(base64.b64encode(payload), binary=False)
        return file_entry

    def test_preview_route_serves_inline(self):
        file_entry = self._setup_file()
        res = self.url_open("/one_storage/entry/%s/preview" % file_entry.id, timeout=12)
        self.assertEqual(res.status_code, 200)
        self.assertIn("inline", res.headers.get("Content-Disposition", ""))
        self.assertEqual(res.content, b"hello")

    def test_download_route_unknown_id_is_404(self):
        self.authenticate("admin", "admin")
        res = self.url_open("/one_storage/entry/99999999/download", timeout=12)
        self.assertEqual(res.status_code, 404)

    def test_preview_route_unknown_id_is_404(self):
        self.authenticate("admin", "admin")
        res = self.url_open("/one_storage/entry/99999999/preview", timeout=12)
        self.assertEqual(res.status_code, 404)

    def test_download_route_directory_is_404(self):
        self.authenticate("admin", "admin")
        self.env["one.storage.entry"].search([("parent_id", "=", False)]).unlink()
        backend = self.env["storage.backend"].create(
            {"name": "Dir FS", "backend_type": "filesystem",
             "directory_path": "one_storage_dir_test_%s" % self.env.cr.dbname}
        )
        root = self.env["one.storage.entry"].create(
            {"name": "root", "entry_type": "directory"}
        )
        backend.entry_id = root
        res = self.url_open("/one_storage/entry/%s/download" % root.id, timeout=12)
        self.assertEqual(res.status_code, 404)
