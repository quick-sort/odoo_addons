# Copyright 2026 One Storage
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

from odoo.addons.queue_job.tests.common import trap_jobs

from .common import OneStorageCommon


class TestRecursiveSync(OneStorageCommon):
    """_sync_from_backend mirrors the whole backend subtree into entries."""

    def test_materializes_nested_dirs_and_files(self):
        self._write_on_disk("a/d.txt", b"ddd")
        self._write_on_disk("a/b/c.txt", b"ccc")
        self.root_folder._sync_from_backend()
        a = self.root_folder.child_ids.filtered(lambda c: c.name == "a")
        self.assertTrue(a and a.is_dir)
        d = a.child_ids.filtered(lambda c: c.name == "d.txt")
        self.assertTrue(d and not d.is_dir)
        self.assertEqual(d.file_size, len(b"ddd"))
        self.assertEqual(d.mimetype, "text/plain")
        b = a.child_ids.filtered(lambda c: c.name == "b")
        self.assertTrue(b and b.is_dir)
        c = b.child_ids.filtered(lambda ch: ch.name == "c.txt")
        self.assertTrue(c and not c.is_dir)
        self.assertEqual(c.file_size, len(b"ccc"))

    def test_sync_is_idempotent(self):
        self._write_on_disk("note.txt", b"x")
        self.root_folder._sync_from_backend()
        self.root_folder._sync_from_backend()
        notes = self.root_folder.child_ids.filtered(lambda c: c.name == "note.txt")
        self.assertEqual(len(notes), 1)


class TestMountWizard(OneStorageCommon):
    """The Mount wizard creates a mount and enqueues an async sync."""

    def test_action_apply_creates_mount_and_enqueues_sync(self):
        second = self.env["storage.backend"].create(
            {
                "name": "Mounted FS",
                "backend_type": "filesystem",
                "directory_path": "mounted_fs_%s" % self.tmp_name,
            }
        )
        wizard = (
            self.env["one.storage.entry.mount.wizard"]
            .with_context(default_entry_id=self.root_folder.id)
            .create({"backend_id": second.id, "backend_path": ""})
        )
        with trap_jobs() as trap:
            res = wizard.action_apply()
            trap.assert_jobs_count(1)
            trap.assert_enqueued_job(
                self.env["one.storage.entry"]._sync_from_backend
            )
        self.assertEqual(res.get("type"), "ir.actions.act_window_close")
        mount = self.env["one.storage.mount"].search(
            [("entry_id", "=", self.root_folder.id), ("backend_id", "=", second.id)]
        )
        self.assertTrue(mount)
