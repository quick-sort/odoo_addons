"""Durable webhook inbox for asynchronous tasks."""

import base64
import logging

from odoo import _, fields, models
from odoo.addons.queue_job.exception import RetryableJobError

_logger = logging.getLogger(__name__)


class AsyncTaskEvent(models.Model):
    _name = "async.task.event"
    _description = "Async Task Webhook Event"
    _order = "received_at desc, id desc"

    task_id = fields.Many2one(
        "async.task",
        required=True,
        index=True,
        ondelete="cascade",
    )
    task_generation = fields.Integer(required=True, readonly=True, index=True)
    event_key = fields.Char(required=True, index=True)
    state = fields.Selection(
        [
            ("pending", "Pending"),
            ("processing", "Processing"),
            ("processed", "Processed"),
            ("ignored", "Ignored"),
            ("failed", "Failed"),
        ],
        required=True,
        default="pending",
        index=True,
        readonly=True,
    )
    headers = fields.Json(
        default=dict,
        readonly=True,
        groups="async_task.group_async_task_manager",
    )
    raw_body = fields.Binary(
        required=True,
        readonly=True,
        attachment=False,
        groups="async_task.group_async_task_manager",
    )
    received_at = fields.Datetime(
        required=True,
        default=fields.Datetime.now,
        readonly=True,
    )
    processed_at = fields.Datetime(readonly=True)
    error_message = fields.Text(readonly=True)

    _task_event_unique = models.Constraint(
        "UNIQUE(task_id, task_generation, event_key)",
        "This webhook event has already been received for this task generation.",
    )
    _task_event_state_idx = models.Index("(task_id, state)")

    def _engine_write(self, values):
        self.ensure_one()
        self.sudo().write(values)
        self.invalidate_recordset()
        return self

    def _raw_bytes(self):
        self.ensure_one()
        return base64.b64decode(self.raw_body or b"")

    def _enqueue(self):
        self.ensure_one()
        task = self.task_id._execution_record()
        event = (
            self.with_user(task.user_id)
            .with_company(task.company_id)
            .with_context(allowed_company_ids=[task.company_id.id])
        )
        return event.with_delay(
            max_retries=0,
            channel="root.async_task",
            description=_("Process webhook for async task %s", task.display_name),
            identity_key=f"async-task-webhook-{self.id}",
        )._job_process()

    def _job_process(self):
        self.ensure_one()
        self.env.cr.execute(
            "SELECT id FROM async_task_event WHERE id = %s FOR UPDATE",
            [self.id],
        )
        self.invalidate_recordset()
        if self.state not in {"pending", "failed"}:
            return

        task = self.task_id
        task._lock_for_update()
        if task.generation != self.task_generation:
            self._engine_write(
                {
                    "state": "ignored",
                    "processed_at": fields.Datetime.now(),
                    "error_message": _("Event belongs to an older task generation."),
                }
            )
            return
        if task.state in task._terminal_states():
            self._engine_write(
                {
                    "state": "ignored",
                    "processed_at": fields.Datetime.now(),
                    "error_message": _("Task was already terminal."),
                }
            )
            return
        if task._deadline_reached():
            task._mark_expired(_("The asynchronous task deadline was reached."))
            self._engine_write(
                {
                    "state": "ignored",
                    "processed_at": fields.Datetime.now(),
                    "error_message": _("Task deadline was reached."),
                }
            )
            return

        self._engine_write({"state": "processing", "error_message": False})
        try:
            adapter = task._resolve_component(task.adapter_usage)
            with self.env.cr.savepoint():
                outcome = adapter.parse_webhook(
                    task,
                    self.sudo().headers or {},
                    self.sudo()._raw_bytes(),
                )
                task._apply_outcome(outcome)
            self._engine_write(
                {
                    "state": "processed",
                    "processed_at": fields.Datetime.now(),
                }
            )
        except RetryableJobError:
            raise
        except Exception as exc:  # noqa: BLE001 - component boundary
            task.invalidate_recordset()
            _logger.exception("Failed to process webhook event %s", self.id)
            self._engine_write(
                {
                    "state": "failed",
                    "processed_at": fields.Datetime.now(),
                    "error_message": str(exc),
                }
            )
            task._mark_failed_from_exception(exc)
