# Copyright 2026 One Storage
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

from odoo.addons.queue_job.tests.common import trap_jobs

from .common import OneStorageCommon


class TestBatchOperations(OneStorageCommon):
    def test_batch_delete_enqueues_job(self):
        self._write_on_disk("to_delete.txt", b"bye")
        entry = self.env["one.storage.entry"].create(
            {"name": "to_delete.txt", "entry_type": "file",
             "parent_id": self.root_folder.id}
        )
        with trap_jobs() as trap:
            entry.action_batch_delete()
            trap.assert_jobs_count(1)
            trap.assert_enqueued_job(entry._batch_delete)
            trap.perform_enqueued_jobs()
        self.assertFalse(entry.exists())

    def test_backend_sync_enqueues_bfs_jobs(self):
        self._write_on_disk("a/b/c.txt", b"deep")
        with trap_jobs() as trap:
            self.backend.action_sync_file_tree()
            trap.assert_jobs_count(1)
            trap.assert_enqueued_job(
                self.backend._sync_folder_level, args=(self.root_folder.id,)
            )
            trap.perform_enqueued_jobs()
            # Breadth-first: root's job enqueues "a", "a" enqueues "b",
            # "b" enqueues "c.txt" — one folder per job per level.
            a = self.root_folder.child_ids.filtered(lambda c: c.name == "a")
            trap.assert_enqueued_job(
                self.backend._sync_folder_level, args=(a.id,)
            )
            trap.perform_enqueued_jobs()
            b = self.env["one.storage.entry"].search(
                [("name", "=", "b"), ("is_dir", "=", True)]
            )
            trap.assert_enqueued_job(
                self.backend._sync_folder_level, args=(b.id,)
            )
            trap.perform_enqueued_jobs()
        c = self.env["one.storage.entry"].search(
            [("name", "=", "c.txt"), ("is_dir", "=", False)]
        )
        self.assertTrue(c)

    def test_sync_job_skips_deleted_entry(self):
        """A queued job whose folder was deleted skips instead of failing."""
        self._write_on_disk("a/b.txt", b"x")
        with trap_jobs() as trap:
            self.backend.action_sync_file_tree()
            trap.perform_enqueued_jobs()  # enqueues job for subdir "a"
            a = self.root_folder.child_ids.filtered(lambda c: c.name == "a")
            a.unlink()
            trap.perform_enqueued_jobs()  # must not raise
        self.assertFalse(a.exists())

    def test_operation_run_creates_job(self):
        op = self.env["one.storage.operation"].create(
            {"name": "test sync", "operation_type": "sync",
             "entry_id": self.root_folder.id}
        )
        with trap_jobs() as trap:
            op.action_run()
            trap.assert_jobs_count(1)
        self.assertEqual(op.state, "pending")
        self.assertTrue(op.job_uuid)
