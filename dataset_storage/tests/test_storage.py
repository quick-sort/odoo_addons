import base64
from unittest import mock

from odoo import Command
from odoo.exceptions import AccessError, ValidationError
from odoo.addons.component.tests.common import TransactionComponentCase


class DatasetStorageCase(TransactionComponentCase):
    @classmethod
    def setUpClass(cls):
        super().setUpClass()
        cls.source = cls.env["dataset.source"].create(
            {"name": "Test", "code": "test"}
        )
        cls.backend = cls.env.ref("dataset_storage.default_storage_backend")
        main_company = cls.env.ref("base.main_company")
        cls.restricted_user = cls.env["res.users"].create(
            {
                "name": "Restricted Dataset User",
                "login": "restricted_dataset_user",
                "company_id": main_company.id,
                "company_ids": [Command.set([main_company.id])],
                "group_ids": [Command.set([cls.env.ref("base.group_user").id])],
            }
        )

    def _dataset(self, code="rows", key_fields=None, chunk_type="parquet"):
        return self.env["dataset"].create(
            {
                "name": code,
                "code": code,
                "source_id": self.source.id,
                "chunk_type": chunk_type,
                "key_fields": key_fields or [],
                "storage_id": self.backend.id,
            }
        )

    def test_default_backend_and_dataset_size(self):
        dataset = self._dataset()
        self.assertEqual(dataset.storage_id, self.backend)
        self.assertEqual(self.backend.directory_path, "datasets")
        self.env["dataset.data_chunk"].create(
            {"dataset_id": dataset.id, "size": 1024**3, "state": "exists"}
        )
        self.assertEqual(dataset.size, 1.0)

    def test_chunk_payload_roundtrip_and_cleanup(self):
        dataset = self._dataset(code="payload", chunk_type="json")
        chunk = self.env["dataset.data_chunk"].create({"dataset_id": dataset.id})
        try:
            chunk.raw_data = base64.b64encode(b"payload")
            self.assertTrue(self.backend.file_exists(chunk.key))
            self.assertEqual(chunk._read_payload(), b"payload")
            self.assertEqual(chunk.state, "exists")
            self.assertEqual(chunk.size, self.backend.get_size(chunk.key))
            chunk.cleanup_raw_data()
            self.assertEqual((chunk.state, chunk.size), ("missing", 0))
        finally:
            if self.backend.file_exists(chunk.key):
                self.backend.delete(chunk.key)

    def test_empty_payload_is_existing(self):
        dataset = self._dataset(code="empty")
        chunk = self.env["dataset.data_chunk"].create({"dataset_id": dataset.id})
        try:
            chunk.raw_data = base64.b64encode(b"")
            self.assertTrue(self.backend.file_exists(chunk.key))
            self.assertEqual(chunk.state, "exists")
            self.assertEqual(chunk.size, 0)
        finally:
            chunk.cleanup_raw_data()

    def test_raw_data_compute_does_not_reconcile_state(self):
        dataset = self._dataset(code="pure")
        chunk = self.env["dataset.data_chunk"].create(
            {"dataset_id": dataset.id, "size": 42, "state": "checked"}
        )
        chunk.invalidate_recordset(["raw_data"])
        with mock.patch.object(type(self.backend), "file_exists", return_value=False):
            self.assertFalse(chunk.raw_data)
        self.assertEqual((chunk.state, chunk.size), ("checked", 42))

    def test_payload_methods_enforce_chunk_access(self):
        dataset = self._dataset(code="secured")
        chunk = self.env["dataset.data_chunk"].create({"dataset_id": dataset.id})
        restricted_chunk = chunk.with_user(self.restricted_user)
        with self.assertRaises(AccessError):
            restricted_chunk.raw_data_exist()
        with self.assertRaises(AccessError):
            restricted_chunk.cleanup_raw_data()

    def test_unlink_requires_explicit_payload_cleanup(self):
        dataset = self._dataset(code="unlink", chunk_type="json")
        chunk = self.env["dataset.data_chunk"].create({"dataset_id": dataset.id})
        chunk.raw_data = base64.b64encode(b"payload")
        with self.assertRaisesRegex(ValidationError, "Delete Stored Payload"):
            chunk.unlink()
        self.assertTrue(chunk.exists())
        chunk.cleanup_raw_data()
        chunk.unlink()

    def test_configuration_write_rejected_while_scan_lock_is_busy(self):
        dataset = self._dataset(code="busy")
        with mock.patch.object(
            type(dataset), "_try_acquire_scan_lock", return_value=False
        ):
            with self.assertRaisesRegex(ValidationError, "reconciliation is active"):
                dataset.write({"storage_id": False})
            with self.assertRaisesRegex(ValidationError, "reconciliation is active"):
                self.source.write({"code": "other"})

    def test_dataset_paths_are_explicitly_logical_at_backend_boundary(self):
        source = self.env["dataset.source"].create(
            {"name": "Root-named source", "code": "datasets"}
        )
        dataset = self.env["dataset"].create(
            {
                "name": "Root path",
                "code": "root-path",
                "source_id": source.id,
                "chunk_type": "parquet",
                "key_fields": ["part"],
                "storage_id": self.backend.id,
            }
        )
        key = dataset.build_chunk_key({"part": "one"})
        backend = dataset._storage_backend()
        try:
            with backend.open(key, "wb") as stream:
                stream.write(b"payload")
            listing = dataset._storage_listing()
            self.assertEqual(len(listing), 1)
            self.assertEqual(listing[0]["name"], key)
            self.assertEqual(listing[0]["size"], 7)
            self.assertFalse(listing[0]["is_dir"])
        finally:
            backend.delete(key)
            backend.rmdir("datasets/root-path")
            backend.rmdir("datasets")

    def test_storage_cannot_change_after_chunks_exist(self):
        dataset = self._dataset(code="fixed-storage")
        self.env["dataset.data_chunk"].create({"dataset_id": dataset.id})
        with self.assertRaisesRegex(ValidationError, "Storage cannot change"):
            dataset.storage_id = False
        dataset.write({"storage_id": self.backend.id})

    def test_keyed_scan_reconciles_in_locked_job(self):
        dataset = self._dataset(code="prices", key_fields=["date"])
        existing = self.env["dataset.data_chunk"].create(
            {
                "dataset_id": dataset.id,
                "metadata": {"date": "2026-01-01"},
                "size": 10,
                "state": "checked",
            }
        )
        missing = self.env["dataset.data_chunk"].create(
            {
                "dataset_id": dataset.id,
                "metadata": {"date": "2026-01-03"},
                "size": 30,
                "state": "exists",
            }
        )
        new_key = "test/prices/2026-01-02.parquet"
        listing = [
            {"name": existing.key, "size": 11, "is_dir": False},
            {"name": new_key, "size": 20, "is_dir": False},
        ]
        sizes = {existing.key: 11, new_key: 20}
        existing_keys = set(sizes)
        with mock.patch.object(
            type(self.backend), "list_files_recursive", return_value=listing
        ), mock.patch.object(
            type(self.backend),
            "file_exists",
            side_effect=lambda key: key in existing_keys,
        ), mock.patch.object(
            type(self.backend), "get_size", side_effect=lambda key: sizes[key]
        ):
            self.assertEqual(dataset.scan_chunks(), 3)
        created = self.env["dataset.data_chunk"].search(
            [("dataset_id", "=", dataset.id), ("key", "=", new_key)]
        )
        self.assertEqual((existing.state, existing.size), ("exists", 11))
        self.assertEqual((missing.state, missing.size), ("missing", 0))
        self.assertEqual((created.state, created.size), ("exists", 20))

    def test_reconciliation_batch_state_transitions(self):
        dataset = self._dataset(code="states", key_fields=["part"])
        changed = self.env["dataset.data_chunk"].create(
            {
                "dataset_id": dataset.id,
                "metadata": {"part": "changed"},
                "size": 1,
                "state": "checked",
            }
        )
        vanished = self.env["dataset.data_chunk"].create(
            {
                "dataset_id": dataset.id,
                "metadata": {"part": "gone"},
                "size": 2,
                "state": "exists",
            }
        )
        with mock.patch.object(
            type(self.backend),
            "file_exists",
            side_effect=lambda key: key == changed.key,
        ), mock.patch.object(type(self.backend), "get_size", return_value=3):
            dataset._scan_update_batch([{"key": changed.key, "size": 3}])
            dataset._scan_missing_batch([{"key": vanished.key}])
        self.assertEqual((changed.state, changed.size), ("exists", 3))
        self.assertEqual((vanished.state, vanished.size), ("missing", 0))

    def test_single_file_scan_uses_exact_calls(self):
        dataset = self._dataset(code="single", chunk_type="csv")
        key = dataset.build_chunk_key({})
        with mock.patch.object(
            type(self.backend), "file_exists", return_value=True
        ) as exists, mock.patch.object(
            type(self.backend), "get_size", return_value=12
        ) as get_size:
            self.assertEqual(
                dataset._storage_listing(),
                [{"name": key, "size": 12, "is_dir": False}],
            )
        exists.assert_called_once_with(key)
        get_size.assert_called_once_with(key)

    def test_scan_button_uses_stable_identity(self):
        dataset = self._dataset(code="queued")
        delayed = mock.MagicMock()
        with mock.patch.object(
            type(dataset), "with_delay", return_value=delayed
        ) as with_delay:
            dataset.action_scan_chunks()
        self.assertEqual(
            with_delay.call_args.kwargs["identity_key"],
            f"dataset_storage:scan:{dataset.id}",
        )
        delayed.scan_chunks.assert_called_once_with()
