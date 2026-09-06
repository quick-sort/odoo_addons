import hashlib
import logging

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.addons.queue_job.exception import RetryableJobError

_logger = logging.getLogger(__name__)
BATCH_SIZE = 1000


class Dataset(models.Model):
    _inherit = "dataset"

    storage_id = fields.Many2one(
        "storage.backend",
        ondelete="restrict",
        default=lambda self: self._get_default_storage(),
        groups="base.group_system",
    )
    size = fields.Float(
        string="Size (GiB)",
        compute="_compute_size",
        store=True,
        readonly=True,
        digits=(16, 3),
    )

    @api.model
    def _get_default_storage(self):
        return self.env.ref(
            "dataset_storage.default_storage_backend", raise_if_not_found=False
        )

    @api.depends("chunk_ids.size")
    def _compute_size(self):
        for record in self:
            total_bytes = sum(record.chunk_ids.mapped("size"))
            record.size = total_bytes / (1024**3) if total_bytes else 0.0

    def write(self, vals):
        protected_fields = {
            "storage_id",
            "source_id",
            "code",
            "chunk_type",
            "key_fields",
        }
        if protected_fields.intersection(vals):
            for record in self:
                if not record._try_acquire_scan_lock():
                    raise ValidationError(
                        _(
                            "Dataset storage and key configuration cannot change "
                            "while reconciliation is active. Retry after the scan "
                            "finishes."
                        )
                    )
        if "storage_id" in vals:
            new_storage_id = vals["storage_id"] or False
            for record in self:
                current_storage_id = record.sudo().storage_id.id or False
                if new_storage_id != current_storage_id and record.chunk_ids:
                    raise ValidationError(
                        _(
                            "Storage cannot change after chunks exist. Clean up or "
                            "move every chunk payload before changing the backend."
                        )
                    )
        return super().write(vals)

    def _storage_backend(self):
        """Return only the configured backend with service-level privileges."""
        self.ensure_one()
        return self.sudo().storage_id.sudo().with_context(
            storage_backend_force_relative_path=True
        )

    def _check_scan_access(self):
        """Enforce catalog ACLs/rules before crossing the backend boundary."""
        self.ensure_one()
        self.check_access("write")
        chunk_model = self.env["dataset.data_chunk"]
        chunks = self.chunk_ids
        chunks.check_access("read")
        chunks.check_access("write")
        chunk_model.browse().check_access("create")

    def _scan_job_identity(self, operation):
        self.ensure_one()
        return f"dataset_storage:{operation}:{self.id}"

    def _scan_lock_key(self):
        self.ensure_one()
        lock_name = f"dataset_storage:scan:{self.id}"
        return int.from_bytes(
            hashlib.sha1(lock_name.encode()).digest()[:8], "big", signed=True
        )

    def _try_acquire_scan_lock(self):
        self.ensure_one()
        self.env.cr.execute(
            "SELECT pg_try_advisory_xact_lock(%s)",
            (self._scan_lock_key(),),
        )
        return self.env.cr.fetchone()[0]

    def _acquire_scan_lock(self):
        """Serialize the complete scan and protected configuration writes."""
        self.ensure_one()
        if not self._try_acquire_scan_lock():
            raise RetryableJobError(
                _("Another storage reconciliation is active for this dataset."),
                seconds=5,
                ignore_retry=True,
            )

    def action_scan_chunks(self):
        self.ensure_one()
        self._check_scan_access()
        if not self._storage_backend():
            raise UserError(_("No storage configured for this dataset."))
        self.with_delay(
            description=_("Reconcile chunks: %s") % self.display_name,
            identity_key=self._scan_job_identity("scan"),
        ).scan_chunks()
        return {
            "type": "ir.actions.client",
            "tag": "display_notification",
            "params": {
                "title": _("Reconciliation scheduled"),
                "message": _(
                    "Storage reconciliation for %s will run in the background."
                )
                % self.display_name,
                "type": "success",
                "sticky": False,
            },
        }

    def _storage_listing(self):
        self.ensure_one()
        backend = self._storage_backend()
        if self.key_fields:
            prefix = f"{self.source_id.code}/{self.code}"
            return backend.list_files_recursive(prefix, detail=True)
        key = self.build_chunk_key({})
        if not backend.file_exists(key):
            return []
        return [{"name": key, "size": backend.get_size(key), "is_dir": False}]

    def _validated_storage_files(self):
        files = {}
        key_fields = self.key_fields or []
        for item in self._storage_listing():
            key = item["name"]
            if key.rsplit(".", 1)[-1] != self.chunk_type:
                continue
            try:
                parsed = self.parse_chunk_key(key, key_fields)
            except ValidationError as error:
                _logger.warning(
                    "Skipping malformed storage key %r for dataset %s: %s",
                    key,
                    self.display_name,
                    error,
                )
                continue
            if (
                parsed["source_code"] != self.source_id.code
                or parsed["dataset_code"] != self.code
                or parsed["chunk_type"] != self.chunk_type
            ):
                _logger.warning(
                    "Skipping storage key %r because it does not identify dataset %s",
                    key,
                    self.display_name,
                )
                continue
            if key in files:
                raise UserError(
                    _("Storage returned duplicate logical chunk key: %s") % key
                )
            files[key] = {
                "key": key,
                "size": item["size"],
                "metadata": parsed["metadata"],
            }
        return files

    def _run_scan_batches(self, rows, method_name):
        rows = sorted(rows, key=lambda row: row["key"])
        processed = 0
        for offset in range(0, len(rows), BATCH_SIZE):
            processed += getattr(self, method_name)(rows[offset : offset + BATCH_SIZE])
        return processed

    def scan_chunks(self):
        """Compare storage and reconcile the catalog in one serialized job."""
        self.ensure_one()
        self._check_scan_access()
        self._acquire_scan_lock()
        if not self._storage_backend():
            raise UserError(_("No storage configured for this dataset."))

        storage_files = self._validated_storage_files()
        existing = {chunk.key: chunk for chunk in self.chunk_ids if chunk.key}
        to_create = []
        to_update = []
        for key, item in storage_files.items():
            chunk = existing.pop(key, False)
            if not chunk:
                to_create.append(item)
            elif chunk.state == "missing" or chunk.size != item["size"]:
                to_update.append({"key": key, "size": item["size"]})
        to_missing = [
            {"key": key}
            for key, chunk in existing.items()
            if chunk.state != "missing" or chunk.size != 0
        ]

        created = self._run_scan_batches(to_create, "_scan_create_batch")
        updated = self._run_scan_batches(to_update, "_scan_update_batch")
        missing = self._run_scan_batches(to_missing, "_scan_missing_batch")
        reconciled = created + updated + missing
        _logger.info(
            "Reconciled dataset %s: %d created, %d refreshed, %d checked missing",
            self.display_name,
            created,
            updated,
            missing,
        )
        return reconciled

    def _scan_create_batch(self, batch):
        self.ensure_one()
        backend = self._storage_backend()
        keys = [item["key"] for item in batch]
        existing = set(
            self.env["dataset.data_chunk"]
            .search([("dataset_id", "=", self.id), ("key", "in", keys)])
            .mapped("key")
        )
        vals_list = []
        for item in batch:
            key = item["key"]
            if key in existing or not backend.file_exists(key):
                continue
            expected_key = self.build_chunk_key(item["metadata"])
            if expected_key != key:
                _logger.warning(
                    "Skipping storage key %r because metadata rebuilds as %r",
                    key,
                    expected_key,
                )
                continue
            vals_list.append(
                {
                    "dataset_id": self.id,
                    "metadata": item["metadata"],
                    "size": backend.get_size(key),
                    "state": "exists",
                    "raw_data_filename": key.rsplit("/", 1)[-1],
                }
            )
        if vals_list:
            self.env["dataset.data_chunk"].create(vals_list)
        return len(vals_list)

    def _scan_update_batch(self, batch):
        self.ensure_one()
        backend = self._storage_backend()
        chunks = self.env["dataset.data_chunk"].search(
            [("dataset_id", "=", self.id), ("key", "in", [row["key"] for row in batch])]
        )
        for chunk in chunks:
            if backend.file_exists(chunk.key):
                chunk.write({"size": backend.get_size(chunk.key), "state": "exists"})
            else:
                chunk.write({"size": 0, "state": "missing"})
        return len(chunks)

    def _scan_missing_batch(self, batch):
        self.ensure_one()
        backend = self._storage_backend()
        chunks = self.env["dataset.data_chunk"].search(
            [("dataset_id", "=", self.id), ("key", "in", [row["key"] for row in batch])]
        )
        for chunk in chunks:
            if backend.file_exists(chunk.key):
                chunk.write({"size": backend.get_size(chunk.key), "state": "exists"})
            else:
                chunk.write({"size": 0, "state": "missing"})
        return len(chunks)
