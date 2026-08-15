# Copyright 2026 ACSONE SA/NV (<http://acsone.eu>)
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl).

import base64

from odoo.exceptions import UserError

from .common import CommonCase


class StorageBackendFileListWizardCase(CommonCase):
    def setUp(self):
        super().setUp()
        self.wizard = self.env["storage.backend.file.list.wizard"].create(
            {"backend_id": self.backend.id}
        )

    def tearDown(self):
        # the filestore is not rolled back with the transaction
        for name in ("wizard/" + self.filename, self.filename):
            if self.backend.file_exists(name):
                self.backend.delete(name)
        super().tearDown()

    def test_upload_with_explicit_path(self):
        self.wizard.write(
            {
                "upload_path": "wizard/" + self.filename,
                "file_data": self.filedata,
                "filename": self.filename,
            }
        )
        self.wizard.action_upload()
        self.assertTrue(self.backend.file_exists("wizard/" + self.filename))
        with self.backend.open("wizard/" + self.filename, "rb") as stream:
            self.assertEqual(stream.read(), base64.b64decode(self.filedata))

    def test_upload_defaults_to_subpath(self):
        self.wizard.write(
            {
                "subpath": "wizard",
                "file_data": self.filedata,
                "filename": self.filename,
            }
        )
        self.wizard.action_upload()
        self.assertTrue(self.backend.file_exists("wizard/" + self.filename))

    def test_upload_without_file(self):
        with self.assertRaises(UserError):
            self.wizard.action_upload()

    def test_upload_refreshes_listing(self):
        self.wizard.write(
            {
                "upload_path": "wizard/" + self.filename,
                "file_data": self.filedata,
                "filename": self.filename,
            }
        )
        action = self.wizard.action_upload()
        self.assertEqual(action["type"], "ir.actions.act_window")
        self.assertIn("wizard/" + self.filename, self.wizard.line_ids.mapped("name"))

    def test_line_download(self):
        self.wizard.write(
            {
                "upload_path": "wizard/" + self.filename,
                "file_data": self.filedata,
                "filename": self.filename,
            }
        )
        self.wizard.action_upload()
        line = self.wizard.line_ids.filtered(
            lambda l: l.name == "wizard/" + self.filename
        )
        action = line.action_download()
        self.assertEqual(action["type"], "ir.actions.act_url")
        self.assertIn("/web/content/", action["url"])
        attachment = self.env["ir.attachment"].browse(
            int(action["url"].split("/web/content/")[1].split("?")[0])
        )
        self.assertEqual(
            base64.b64decode(attachment.datas), base64.b64decode(self.filedata)
        )
        self.assertEqual(attachment.name, self.filename)

    def test_line_download_missing_file(self):
        line = self.wizard.line_ids.new({"name": "no_such_file.bin"})
        with self.assertRaises((FileNotFoundError, UserError)):
            line.action_download()

    def test_line_delete(self):
        self.wizard.write(
            {
                "upload_path": "wizard/" + self.filename,
                "file_data": self.filedata,
                "filename": self.filename,
            }
        )
        self.wizard.action_upload()
        line = self.wizard.line_ids.filtered(
            lambda l: l.name == "wizard/" + self.filename
        )
        action = line.action_delete()
        self.assertEqual(action["type"], "ir.actions.act_window")
        self.assertFalse(self.backend.file_exists("wizard/" + self.filename))
        self.assertNotIn("wizard/" + self.filename, self.wizard.line_ids.mapped("name"))

    def test_line_download_in_subpath_uses_full_path(self):
        # adapters list names relative to the browsed path: listing
        # "wizard" shows "test_file.txt", but the backend path is
        # "wizard/test_file.txt" — download must use the full one.
        with self.backend.open("wizard/" + self.filename, "wb") as stream:
            stream.write(base64.b64decode(self.filedata))
        self.wizard.subpath = "wizard"
        self.wizard.action_list_files()
        line = self.wizard.line_ids.filtered(lambda l: l.name == self.filename)
        self.assertTrue(line)
        self.assertEqual(line.relative_path, "wizard/" + self.filename)
        action = line.action_download()
        self.assertEqual(action["type"], "ir.actions.act_url")
        attachment = self.env["ir.attachment"].browse(
            int(action["url"].split("/web/content/")[1].split("?")[0])
        )
        self.assertEqual(
            base64.b64decode(attachment.datas), base64.b64decode(self.filedata)
        )

    def test_line_delete_in_subpath_uses_full_path(self):
        with self.backend.open("wizard/" + self.filename, "wb") as stream:
            stream.write(base64.b64decode(self.filedata))
        self.wizard.subpath = "wizard"
        self.wizard.action_list_files()
        line = self.wizard.line_ids.filtered(lambda l: l.name == self.filename)
        line.action_delete()
        self.assertFalse(self.backend.file_exists("wizard/" + self.filename))

    def test_refresh_keeps_line_ids_stable(self):
        # S3 listings can be slow; the browser may render a listing from
        # before a refresh landed. If refresh wiped and recreated the lines,
        # row buttons from the stale rendering would hit deleted records.
        self.wizard.write(
            {
                "upload_path": "wizard/" + self.filename,
                "file_data": self.filedata,
                "filename": self.filename,
            }
        )
        self.wizard.action_upload()
        line = self.wizard.line_ids.filtered(
            lambda l: l.name == "wizard/" + self.filename
        )
        ids_before = set(self.wizard.line_ids.ids)
        self.wizard.action_list_files()
        self.assertEqual(set(self.wizard.line_ids.ids), ids_before)
        # the stale rendering's line is still alive and downloadable
        action = line.action_download()
        self.assertEqual(action["type"], "ir.actions.act_url")

    def test_refresh_syncs_added_and_removed_files(self):
        names = ["sync_a.txt", "sync_b.txt"]
        for name in names:
            with self.backend.open(name, "wb") as stream:
                stream.write(b"x")
        try:
            self.wizard.action_list_files()
            line_a = self.wizard.line_ids.filtered(lambda l: l.name == "sync_a.txt")
            self.assertTrue(line_a)
            self.backend.delete("sync_a.txt")
            with self.backend.open("sync_c.txt", "wb") as stream:
                stream.write(b"y")
            self.wizard.action_list_files()
            self.assertFalse(
                self.wizard.line_ids.filtered(lambda l: l.name == "sync_a.txt")
            )
            self.assertTrue(
                self.wizard.line_ids.filtered(lambda l: l.name == "sync_c.txt")
            )
            self.assertTrue(
                self.wizard.line_ids.filtered(lambda l: l.name == "sync_b.txt")
            )
        finally:
            for name in ("sync_b.txt", "sync_c.txt"):
                if self.backend.file_exists(name):
                    self.backend.delete(name)
