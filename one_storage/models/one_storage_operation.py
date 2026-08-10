# Copyright 2026 One Storage
# License LGPL-3.0 or later (http://www.gnu.org/licenses/lgpl.html)

import logging

from odoo import _, fields, models

_logger = logging.getLogger(__name__)


class OneStorageOperation(models.Model):
    """Tracks an async batch operation over folders/nodes.

    The actual work runs in a queue_job worker via :meth:`action_run`;
    this record stores inputs, state and a link back to the queue job uuid.
    """

    _name = "one.storage.operation"
    _description = "One Storage Batch Operation"
    _order = "create_date desc"

    name = fields.Char(required=True, default=lambda self: _("New operation"))
    operation_type = fields.Selection(
        selection=[
            ("copy", "Copy"),
            ("move", "Move"),
            ("delete", "Delete"),
            ("sync", "Sync"),
            ("upload", "Upload"),
        ],
        required=True,
        default="sync",
    )
    state = fields.Selection(
        selection=[
            ("draft", "Draft"),
            ("pending", "Pending"),
            ("done", "Done"),
            ("failed", "Failed"),
        ],
        default="draft",
    )
    entry_id = fields.Many2one(
        comodel_name="one.storage.entry",
        help="Target directory for sync/move operations.",
    )
    entry_ids = fields.Many2many(
        comodel_name="one.storage.entry",
        help="File entries to delete or move.",
    )
    backend_id = fields.Many2one(comodel_name="storage.backend")
    job_uuid = fields.Char(readonly=True)
    user_id = fields.Many2one(comodel_name="res.users", default=lambda self: self.env.user)
    result_message = fields.Text(readonly=True)

    def action_run(self):
        for op in self:
            op.state = "pending"
            delayable = op.with_delay(
                channel="root.one_storage",
                description=_("Operation %s") % op.display_name,
            )._run_batch()
            op.job_uuid = delayable.uuid

    def _run_batch(self):
        self.ensure_one()
        try:
            files = self.entry_ids.filtered(lambda e: not e.is_dir)
            if self.operation_type == "delete":
                files.unlink()
            elif self.operation_type == "sync":
                if self.entry_id and self.entry_id.is_dir:
                    self.entry_id._sync_from_backend()
            elif self.operation_type == "move":
                if self.entry_id and self.entry_id.is_dir:
                    files.action_batch_move(self.entry_id)
            self.write({"state": "done"})
        except Exception as err:  # noqa: BLE001
            _logger.exception("Operation %s failed", self.display_name)
            self.write({"state": "failed", "result_message": str(err)})

    def action_open_job(self):
        self.ensure_one()
        if not self.job_uuid:
            return False
        job = self.env["queue.job"].search([("uuid", "=", self.job_uuid)], limit=1)
        if not job:
            return False
        return {
            "type": "ir.actions.act_window",
            "res_model": "queue.job",
            "res_id": job.id,
            "view_mode": "form",
            "target": "current",
        }
