"""Logical items contained in an asynchronous task request."""

from uuid import uuid4

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError

ITEM_ENGINE_FIELDS = {
    "state",
    "progress",
    "external_item_id",
    "output_payload",
    "attempt_count",
    "started_at",
    "completed_at",
    "error_message",
}


class AsyncTaskItem(models.Model):
    _name = "async.task.item"
    _description = "Async Task Item"
    _order = "task_id, sequence, id"

    task_id = fields.Many2one(
        "async.task",
        required=True,
        index=True,
        ondelete="cascade",
    )
    sequence = fields.Integer(default=10)
    name = fields.Char(required=True)
    correlation_key = fields.Char(
        required=True,
        default=lambda self: str(uuid4()),
        index=True,
        help="Stable key used to map provider batch results back to this item.",
    )
    idempotency_key = fields.Char(
        required=True,
        default=lambda self: str(uuid4()),
        index=True,
    )
    state = fields.Selection(
        [
            ("pending", "Pending"),
            ("running", "Running"),
            ("succeeded", "Succeeded"),
            ("failed", "Failed"),
            ("cancelled", "Cancelled"),
        ],
        required=True,
        default="pending",
        index=True,
        readonly=True,
    )
    progress = fields.Float(default=0.0, readonly=True)
    external_item_id = fields.Char(index=True, readonly=True)
    resource_model = fields.Char(index=True)
    resource_id = fields.Many2oneReference(model_field="resource_model")
    resource_version = fields.Char(
        help="Checksum or version used to reject stale asynchronous results."
    )
    input_payload = fields.Json(default=dict)
    output_payload = fields.Json(default=dict, readonly=True)
    attempt_count = fields.Integer(default=0, readonly=True)
    started_at = fields.Datetime(readonly=True)
    completed_at = fields.Datetime(readonly=True)
    error_message = fields.Text(readonly=True)

    _task_correlation_unique = models.Constraint(
        "UNIQUE(task_id, correlation_key)",
        "The item correlation key must be unique within a task.",
    )
    _task_item_idempotency_unique = models.Constraint(
        "UNIQUE(task_id, idempotency_key)",
        "The item idempotency key must be unique within a task.",
    )
    _progress_range = models.Constraint(
        "CHECK(progress >= 0 AND progress <= 100)",
        "Item progress must be between 0 and 100.",
    )
    _task_state_idx = models.Index("(task_id, state)")

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            for vals in vals_list:
                if ITEM_ENGINE_FIELDS & vals.keys():
                    raise AccessError(
                        _("Item execution fields can only be initialized by the engine.")
                    )
                task = self.env["async.task"].browse(vals.get("task_id")).exists()
                if task and task.state != "draft":
                    raise UserError(_("Items can only be added to draft tasks."))
        for vals in vals_list:
            vals.setdefault("name", vals.get("correlation_key") or _("Task item"))
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su:
            if ITEM_ENGINE_FIELDS & vals.keys():
                raise AccessError(
                    _("Item execution fields can only be changed by the task engine.")
                )
            if any(item.task_id.state != "draft" for item in self):
                raise UserError(_("Items can only be changed while their task is draft."))
        return super().write(vals)

    def _engine_write(self, values):
        if not self:
            return self
        self.sudo().write(values)
        self.invalidate_recordset()
        return self
