# Copyright 2026 One Storage
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

import logging

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)

OPERATION_TYPE_SELECTION = [
    ("sync_tree", "Sync Tree"),
    ("sync_folder", "Sync Folder"),
    ("delete", "Delete"),
    ("move", "Move"),
    ("upload", "Upload"),
]


class OneStorageOperation(models.Model):
    """Tracks an async batch operation over folders/nodes.

    Created by the UI entry points (sync buttons, delete/move wizards) and
    never run manually: each record immediately enqueues its worker jobs on
    itself. The state is derived from the linked queue jobs.
    """

    _name = "one.storage.operation"
    _description = "One Storage Batch Operation"
    _order = "create_date desc"

    name = fields.Char(required=True, default=lambda self: _("New operation"))
    operation_type = fields.Selection(
        selection=OPERATION_TYPE_SELECTION, required=True, index=True
    )
    state = fields.Selection(
        selection=[
            ("pending", "Pending"),
            ("progress", "In Progress"),
            ("done", "Done"),
            ("failed", "Failed"),
        ],
        compute="_compute_state",
    )
    backend_id = fields.Many2one(comodel_name="storage.backend")
    entry_id = fields.Many2one(
        comodel_name="one.storage.entry",
        string="Target Folder",
        help="Target directory.",
    )
    dest_entry_id = fields.Many2one(
        comodel_name="one.storage.entry", help="Move destination directory."
    )
    entry_ids = fields.Many2many(
        comodel_name="one.storage.entry", help="Entries to delete or move."
    )
    job_ids = fields.One2many(
        comodel_name="one.storage.operation.job",
        inverse_name="operation_id",
        string="Jobs",
    )
    jobs_count = fields.Integer(compute="_compute_jobs_count")
    done_count = fields.Integer(compute="_compute_jobs_count")
    user_id = fields.Many2one(
        comodel_name="res.users", default=lambda self: self.env.user
    )
    result_message = fields.Text()

    @api.depends("job_ids.state")
    def _compute_state(self):
        for op in self:
            states = set(op.job_ids.mapped("state"))
            if not states:
                op.state = "pending"
            elif "failed" in states:
                op.state = "failed"
            elif states <= {"done", "cancelled"}:
                op.state = "done"
            elif "started" in states or "enqueued" in states:
                op.state = "progress"
            else:
                op.state = "pending"

    @api.depends("job_ids.state")
    def _compute_jobs_count(self):
        for op in self:
            op.jobs_count = len(op.job_ids)
            op.done_count = len(
                op.job_ids.filtered(lambda j: j.state in ("done", "cancelled"))
            )

    # ------------------------------------------------------------------
    # Enqueue API — all worker jobs run on the operation record itself
    # ------------------------------------------------------------------
    def _enqueue(self, description, method, *args):
        """Enqueue one worker job on this operation and link it."""
        self.ensure_one()
        delayable = self.with_delay(
            channel="root.one_storage", description=description
        )
        job = getattr(delayable, method)(*args)
        self.env["one.storage.operation.job"].create(
            {
                "operation_id": self.id,
                "job_uuid": job.uuid,
                "name": description,
            }
        )
        return job

    @api.model
    def create_operation(self, operation_type, name, **vals):
        """Create an operation record; jobs are enqueued by the caller."""
        return self.create({"operation_type": operation_type, "name": name, **vals})

    # ------------------------------------------------------------------
    # Worker jobs (queue_job) — one per unit of work
    # ------------------------------------------------------------------
    def _op_sync_folder(self, entry_id):
        """BFS step: sync one folder's children and enqueue each subdir.

        Takes the folder's entry id: entries may be deleted while jobs are
        still queued (e.g. the mirror tree is unmounted and cleared), in
        which case the stale job is skipped instead of failing.
        """
        self.ensure_one()
        op = self.exists()
        if not op:
            return
        entry = self.env["one.storage.entry"].browse(entry_id).exists()
        if not entry or not entry.is_dir:
            return
        entry._sync_children()
        for child in entry.child_ids.filtered("is_dir"):
            op._enqueue(
                _("Sync folder %s") % child.complete_name,
                "_op_sync_folder",
                child.id,
            )

    def _op_delete_entry(self, entry_id):
        """Delete one entry (file or directory recursively) on the backend."""
        self.ensure_one()
        if not self.exists():
            return
        entry = self.env["one.storage.entry"].browse(entry_id).exists()
        if not entry:
            return
        if entry.is_dir:
            entry.rmtree()
        else:
            try:
                backend, _mirror = entry._resolve_backend()
                backend.delete(entry._backend_relpath())
            except Exception as err:  # noqa: BLE001
                _logger.warning(
                    "Backend delete failed for %s: %s", entry.complete_name, err
                )
            entry.unlink()

    def _op_move_entry(self, entry_id, dest_entry_id):
        self.ensure_one()
        if not self.exists():
            return
        entry = self.env["one.storage.entry"].browse(entry_id).exists()
        dest = self.env["one.storage.entry"].browse(dest_entry_id).exists()
        if not entry or not dest or not dest.is_dir:
            return
        entry.move(dest)

    def _op_upload_file(self, entry_id, datas):
        self.ensure_one()
        if not self.exists():
            return
        entry = self.env["one.storage.entry"].browse(entry_id).exists()
        if entry:
            entry.set_content(datas, binary=False)

    # ------------------------------------------------------------------
    # High-level entry points used by UI actions and wizards
    # ------------------------------------------------------------------
    @api.model
    def start_sync_tree(self, backend, root):
        op = self.create_operation(
            "sync_tree",
            _("Sync tree: %s") % backend.display_name,
            backend_id=backend.id,
            entry_id=root.id,
        )
        op._enqueue(
            _("Sync file tree of %s") % backend.display_name,
            "_op_sync_folder",
            root.id,
        )
        return op

    @api.model
    def start_delete(self, entries):
        name = (
            _("Delete: %s") % entries[:1].complete_name
            if len(entries) == 1
            else _("Delete %s entries") % len(entries)
        )
        op = self.create_operation(
            "delete", name, entry_ids=[(6, 0, entries.ids)]
        )
        for entry in entries:
            op._enqueue(
                _("Delete %s") % entry.complete_name, "_op_delete_entry", entry.id
            )
        return op

    @api.model
    def start_move(self, entries, dest):
        op = self.create_operation(
            "move",
            _("Move %s entries to %s") % (len(entries), dest.complete_name),
            dest_entry_id=dest.id,
            entry_ids=[(6, 0, entries.ids)],
        )
        for entry in entries:
            op._enqueue(
                _("Move %s") % entry.complete_name,
                "_op_move_entry",
                entry.id,
                dest.id,
            )
        return op

    def action_open_jobs(self):
        self.ensure_one()
        return {
            "type": "ir.actions.act_window",
            "name": _("Jobs"),
            "res_model": "one.storage.operation.job",
            "view_mode": "list",
            "domain": [("operation_id", "=", self.id)],
            "target": "current",
        }


class OneStorageOperationJob(models.Model):
    """Bridge between an operation and its queue.job."""

    _name = "one.storage.operation.job"
    _description = "One Storage Operation Job"
    _order = "id asc"

    operation_id = fields.Many2one(
        comodel_name="one.storage.operation",
        required=True,
        ondelete="cascade",
        index=True,
    )
    name = fields.Char()
    job_uuid = fields.Char(required=True, index=True)
    queue_job_id = fields.Many2one(
        comodel_name="queue.job",
        compute="_compute_queue_job",
        string="Queue Job",
    )
    state = fields.Selection(
        selection=[
            ("pending", "Pending"),
            ("enqueued", "Enqueued"),
            ("started", "Started"),
            ("done", "Done"),
            ("cancelled", "Cancelled"),
            ("failed", "Failed"),
        ],
        compute="_compute_job_state",
    )
    exc_message = fields.Char(compute="_compute_job_state")

    def _compute_job_state(self):
        jobs = self.env["queue.job"]
        for rec in self:
            job = jobs.search([("uuid", "=", rec.job_uuid)], limit=1)
            rec.queue_job_id = job
            rec.state = job.state
            rec.exc_message = job.exc_message

    def action_open_job(self):
        self.ensure_one()
        if not self.queue_job_id:
            return False
        return {
            "type": "ir.actions.act_window",
            "res_model": "queue.job",
            "res_id": self.queue_job_id.id,
            "view_mode": "form",
            "target": "current",
        }
