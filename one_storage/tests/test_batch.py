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
            trap.assert_enqueued_job(
                self.env["one.storage.entry"]._batch_delete
            )
            trap.perform_enqueued_jobs()
        self.assertFalse(entry.exists())

    def test_folder_sync_enqueues_job(self):
        with trap_jobs() as trap:
            self.root_folder.action_sync_from_backend()
            trap.assert_jobs_count(1)
            trap.assert_enqueued_job(
                self.env["one.storage.entry"]._sync_from_backend
            )

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
