# Copyright 2026 One Storage
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

import os

from .common import OneStorageCommon


class TestSyncRefreshAndPrune(OneStorageCommon):
    def test_sync_prunes_deleted_backend_files(self):
        self._write_on_disk("gone.txt", b"bye")
        self.root_folder._sync_from_backend()
        self.assertTrue(self.root_folder.child_ids.filtered(
            lambda c: c.name == "gone.txt"
        ))
        os.remove(os.path.join(self.tmpdir, "gone.txt"))
        self.root_folder._sync_from_backend_path(
            self.backend, self.root_folder._backend_relpath()
        )
        self.assertFalse(self.root_folder.child_ids.filtered(
            lambda c: c.name == "gone.txt"
        ))

    def test_sync_keeps_draft_entries(self):
        entry = self.root_folder.create_file("placeholder.txt")
        self.root_folder._sync_from_backend()
        self.assertTrue(entry.exists())

    def test_sync_keeps_logical_dirs(self):
        folder = self.root_folder.mkdir("logical")
        self.root_folder._sync_from_backend()
        self.assertTrue(folder.exists())

    def test_sync_refreshes_existing_file_metadata(self):
        self._write_on_disk("a.txt", b"12345")
        self.root_folder._sync_from_backend()
        entry = self.root_folder.child_ids.filtered(lambda c: c.name == "a.txt")
        self.assertEqual(entry.file_size, 5)
        self._write_on_disk("a.txt", b"1234567890")
        self.root_folder._sync_from_backend()
        entry = self.root_folder.child_ids.filtered(lambda c: c.name == "a.txt")
        self.assertEqual(len(entry), 1)
        self.assertEqual(entry.file_size, 10)
        self.assertEqual(entry.state, "synced")

    def test_lazy_sync_via_list_children_skips_backend_when_disabled(self):
        self._write_on_disk("lazy.txt", b"x")
        children = self.root_folder.list_children(sync=False)
        self.assertNotIn("lazy.txt", children.mapped("name"))
        children = self.root_folder.list_children(sync=True)
        self.assertIn("lazy.txt", children.mapped("name"))
