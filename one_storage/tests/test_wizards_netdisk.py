# Copyright 2026 One Storage
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

import base64
from unittest.mock import patch

from odoo.addons.queue_job.tests.common import trap_jobs
from odoo.exceptions import ValidationError

from .common import OneStorageCommon


class TestCreateWizard(OneStorageCommon):
    def _wizard(self, values):
        return (
            self.env["one.storage.entry.create.wizard"]
            .with_context(default_parent_id=self.root_folder.id)
            .create(values)
        )

    def test_create_folder(self):
        self._wizard({"folder_name": "projects"}).action_apply()
        folder = self.root_folder.child_ids.filtered(
            lambda c: c.name == "projects"
        )
        self.assertTrue(folder and folder.is_dir)

    def test_upload_file_into_folder(self):
        self._wizard(
            {"datas": base64.b64encode(b"content"), "filename": "up.txt"}
        ).action_apply()
        entry = self.root_folder.child_ids.filtered(
            lambda c: c.name == "up.txt"
        )
        self.assertTrue(entry and not entry.is_dir)
        self.assertEqual(entry.read_bytes(), b"content")
        self.assertEqual(entry.state, "synced")

    def test_folder_plus_file_nests_file(self):
        self._wizard(
            {
                "folder_name": "newdir",
                "datas": base64.b64encode(b"x"),
                "filename": "inner.txt",
            }
        ).action_apply()
        folder = self.root_folder.resolve_path(["newdir"])
        entry = folder.child_ids.filtered(lambda c: c.name == "inner.txt")
        self.assertTrue(entry)
        self.assertEqual(entry.read_bytes(), b"x")

    def test_upload_overwrites_existing_file(self):
        self.root_folder.create_file("up.txt", b"old")
        self._wizard(
            {"datas": base64.b64encode(b"new"), "filename": "up.txt"}
        ).action_apply()
        entry = self.root_folder.child_ids.filtered(lambda c: c.name == "up.txt")
        self.assertEqual(entry.read_bytes(), b"new")

    def test_empty_wizard_raises(self):
        with self.assertRaises(ValidationError):
            self._wizard({}).action_apply()


class TestRenameWizard(OneStorageCommon):
    def test_rename_wizard_renames(self):
        entry = self.root_folder.create_file("old.txt", b"data")
        wizard = (
            self.env["one.storage.entry.rename.wizard"]
            .with_context(default_entry_id=entry.id)
            .create({"new_name": "new.txt"})
        )
        wizard.action_apply()
        self.assertEqual(entry.name, "new.txt")
        self.assertTrue(self.backend.file_exists("new.txt"))


class TestMoveWizard(OneStorageCommon):
    def test_move_wizard_moves_entries(self):
        dest = self.root_folder.mkdir("dest")
        a = self.root_folder.create_file("a.txt", b"1")
        b = self.root_folder.create_file("b.txt", b"2")
        wizard = (
            self.env["one.storage.entry.move.wizard"]
            .with_context(default_entry_ids=[(6, 0, (a | b).ids)])
            .create({"dest_dir_id": dest.id})
        )
        with trap_jobs() as trap:
            wizard.action_apply()
            trap.perform_enqueued_jobs()
        self.assertEqual(a.parent_id, dest)
        self.assertEqual(b.parent_id, dest)
        self.assertTrue(self.backend.file_exists("dest/a.txt"))
        self.assertTrue(self.backend.file_exists("dest/b.txt"))


class TestDeleteWizardMulti(OneStorageCommon):
    def test_delete_wizard_recursive(self):
        folder = self.root_folder.mkdir("tree")
        folder.create_file("a.txt", b"x")
        wizard = (
            self.env["one.storage.entry.delete.wizard"]
            .with_context(default_entry_ids=[(6, 0, folder.ids)])
            .create({"recursive": True})
        )
        with trap_jobs() as trap:
            wizard.action_apply()
            trap.perform_enqueued_jobs()
        self.assertFalse(folder.exists())
        self.assertFalse(self.backend.file_exists("tree/a.txt"))

    def test_delete_wizard_non_recursive_blocked(self):
        folder = self.root_folder.mkdir("tree")
        folder.create_file("a.txt", b"x")
        wizard = (
            self.env["one.storage.entry.delete.wizard"]
            .with_context(default_entry_ids=[(6, 0, folder.ids)])
            .create({"recursive": False})
        )
        with self.assertRaises(ValidationError):
            wizard.action_apply()
        self.assertTrue(folder.exists())

class TestMountWizard(OneStorageCommon):
    def _make_second_backend(self):
        second = self.env["storage.backend"].create(
            {
                "name": "Second FS",
                "backend_type": "filesystem",
                "directory_path": "second_fs_%s" % self.tmp_name,
            }
        )
        import os

        subdir = os.path.join(
            second._get_adapter()._basedir(), second.directory_path
        )
        os.makedirs(subdir, exist_ok=True)
        with open(os.path.join(subdir, "remote.txt"), "wb") as fh:
            fh.write(b"from-backend")
        return second

    def _wizard(self, folder, values=None):
        return (
            self.env["one.storage.entry.mount.wizard"]
            .with_context(default_entry_id=folder.id)
            .create(values or {})
        )

    def test_mount_binds_to_hidden_mirror(self):
        second = self._make_second_backend()
        folder = self.root_folder.mkdir("mnt")
        self._wizard(folder, {"backend_id": second.id}).action_mount()
        self.assertTrue(folder.binding_id)
        self.assertEqual(folder.binding_id.backend_id, second)
        self.assertEqual(second.entry_id, folder.binding_id)
        # The computed backend_id shows the bound backend (kanban badge).
        self.assertEqual(folder.backend_id, second)
        # The mirror root is hidden from the browser.
        self.assertFalse(folder.binding_id.active)
        # First listing lazily pulls one level from the backend.
        entry = folder.list_children().filtered(lambda c: c.name == "remote.txt")
        self.assertTrue(entry)
        self.assertEqual(entry.read_bytes(), b"from-backend")

    def test_mount_makes_no_backend_calls(self):
        """Mounting must not scan the backend: the tree fills lazily."""
        second = self._make_second_backend()
        folder = self.root_folder.mkdir("mnt")
        with patch("odoo.addons.storage_backend.models.storage_backend."
                   "StorageBackend.list_files") as mocked:
            self._wizard(folder, {"backend_id": second.id}).action_mount()
            mocked.assert_not_called()

    def test_unmount_keeps_mirror_tree_for_remount(self):
        second = self._make_second_backend()
        folder = self.root_folder.mkdir("mnt")
        self._wizard(folder, {"backend_id": second.id}).action_mount()
        folder.list_children()  # materialize one level
        wizard = self._wizard(folder, {"backend_id": second.id})
        self.assertTrue(wizard.is_mounted)
        wizard.action_unmount()
        self.assertFalse(folder.binding_id)
        # Remount rebinds instantly: the mirror tree survives, no rescan.
        with patch("odoo.addons.storage_backend.models.storage_backend."
                   "StorageBackend.list_files") as mocked:
            self._wizard(folder, {"backend_id": second.id}).action_mount()
            mocked.assert_not_called()
        entry = folder.list_children(sync=False).filtered(
            lambda c: c.name == "remote.txt"
        )
        self.assertTrue(entry)

    def test_lazy_one_level_only(self):
        """Listing the mount pulls one level; nested content waits."""
        import os

        second = self._make_second_backend()
        base = os.path.join(
            second._get_adapter()._basedir(), second.directory_path
        )
        os.makedirs(os.path.join(base, "deep", "deeper"), exist_ok=True)
        with open(os.path.join(base, "deep", "leaf.txt"), "wb") as fh:
            fh.write(b"leaf")
        folder = self.root_folder.mkdir("mnt")
        self._wizard(folder, {"backend_id": second.id}).action_mount()
        children = folder.list_children()
        self.assertIn("remote.txt", children.mapped("name"))
        self.assertIn("deep", children.mapped("name"))
        deep = children.filtered(lambda c: c.name == "deep")
        self.assertFalse(deep.child_ids, "nested level must not be scanned yet")
        leafs = deep.list_children().filtered(lambda c: c.name == "leaf.txt")
        self.assertTrue(leafs)

    def test_mount_on_file_rejected(self):
        second = self._make_second_backend()
        entry = self.root_folder.create_file("f.txt", b"x")
        wizard = self._wizard(entry, {"backend_id": second.id})
        with self.assertRaises(ValidationError):
            wizard.action_mount()

    def test_mount_twice_rejected(self):
        second = self._make_second_backend()
        folder = self.root_folder.mkdir("mnt")
        self._wizard(folder, {"backend_id": second.id}).action_mount()
        third = self.env["storage.backend"].create(
            {"name": "Third", "backend_type": "filesystem"}
        )
        wizard = self._wizard(folder, {"backend_id": third.id})
        with self.assertRaises(ValidationError):
            wizard.action_mount()

    def test_unmount_without_backend_rejected(self):
        folder = self.root_folder.mkdir("plain")
        wizard = self._wizard(folder, {"backend_id": self.backend.id})
        with self.assertRaises(ValidationError):
            wizard.action_unmount()
