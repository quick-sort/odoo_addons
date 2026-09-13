"""Persistent, component-driven asynchronous task lifecycle."""

import logging
import secrets
from contextlib import contextmanager
from datetime import timedelta
from uuid import uuid4

from odoo import _, api, fields, models
from odoo.exceptions import AccessError, UserError, ValidationError
from odoo.addons.component.exception import NoComponentError, RegistryNotReadyError
from odoo.addons.queue_job.exception import RetryableJobError

_logger = logging.getLogger(__name__)

TERMINAL_STATES = {
    "succeeded",
    "partially_succeeded",
    "failed",
    "blocked",
    "cancelled",
    "expired",
}
SUCCESS_STATES = {"succeeded"}
ENGINE_FIELDS = {
    "state",
    "wait_mode",
    "generation",
    "external_task_id",
    "external_status",
    "progress",
    "attempt_count",
    "poll_count",
    "submitted_at",
    "started_at",
    "completed_at",
    "next_poll_at",
    "output_payload",
    "adapter_metadata",
    "error_type",
    "error_message",
}
CONFIG_FIELDS = {
    "task_type",
    "adapter_usage",
    "handler_usage",
    "dependency_policy",
    "dependency_ids",
    "user_id",
    "company_id",
    "priority",
    "queue_channel",
    "idempotency_key",
    "webhook_token",
    "max_poll_count",
    "poll_interval",
    "timeout_at",
    "resource_model",
    "resource_id",
    "resource_version",
    "input_payload",
    "item_ids",
}

ALLOWED_TRANSITIONS = {
    "draft": {"waiting_dependencies", "queued", "cancelled", "expired"},
    "waiting_dependencies": {"queued", "blocked", "cancelled", "expired"},
    "queued": {"submitting", "cancelled", "expired"},
    "submitting": {
        "waiting",
        "succeeded",
        "partially_succeeded",
        "failed",
        "cancel_pending",
        "cancelled",
        "expired",
    },
    "running": {
        "waiting",
        "succeeded",
        "partially_succeeded",
        "failed",
        "cancel_pending",
        "cancelled",
        "expired",
    },
    "waiting": {
        "running",
        "succeeded",
        "partially_succeeded",
        "failed",
        "cancel_pending",
        "cancelled",
        "expired",
    },
    "cancel_pending": {
        "running",
        "waiting",
        "succeeded",
        "partially_succeeded",
        "failed",
        "cancelled",
        "expired",
    },
    "succeeded": set(),
    "partially_succeeded": {"draft", "cancelled"},
    "failed": {"draft", "cancelled"},
    "blocked": {"draft", "waiting_dependencies", "queued", "cancelled"},
    "cancelled": {"draft"},
    "expired": {"draft", "cancelled"},
}


class AsyncTask(models.Model):
    _name = "async.task"
    _description = "Asynchronous Task"
    _inherit = ["collection.base"]
    _order = "create_date desc, id desc"

    name = fields.Char(required=True, index=True)
    active = fields.Boolean(default=True)
    task_type = fields.Char(
        required=True,
        index=True,
        help="Domain-defined operation type. The engine does not interpret it.",
    )
    adapter_usage = fields.Char(
        required=True,
        index=True,
        help="Component usage implementing the external operation protocol.",
    )
    handler_usage = fields.Char(
        required=True,
        default="async_task.handler.noop",
        index=True,
        help="Component usage applying normalized results to business records.",
    )
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("waiting_dependencies", "Waiting for Dependencies"),
            ("queued", "Queued"),
            ("submitting", "Submitting"),
            ("running", "Running"),
            ("waiting", "Waiting for Remote Completion"),
            ("cancel_pending", "Cancellation Pending"),
            ("succeeded", "Succeeded"),
            ("partially_succeeded", "Partially Succeeded"),
            ("failed", "Failed"),
            ("blocked", "Blocked"),
            ("cancelled", "Cancelled"),
            ("expired", "Expired"),
        ],
        required=True,
        default="draft",
        index=True,
        readonly=True,
    )
    wait_mode = fields.Selection(
        [
            ("none", "None"),
            ("poll", "Polling"),
            ("webhook", "Webhook"),
            ("manual", "Manual"),
        ],
        required=True,
        default="none",
        readonly=True,
    )
    dependency_policy = fields.Selection(
        [
            ("all_succeeded", "All dependencies must succeed"),
            ("all_terminal", "Run after all dependencies finish"),
        ],
        required=True,
        default="all_succeeded",
    )

    user_id = fields.Many2one(
        "res.users",
        required=True,
        default=lambda self: self.env.user,
        index=True,
    )
    company_id = fields.Many2one(
        "res.company",
        required=True,
        default=lambda self: self.env.company,
        index=True,
    )
    priority = fields.Integer(default=10)
    queue_channel = fields.Char(required=True, default="root.async_task")

    idempotency_key = fields.Char(
        required=True,
        default=lambda self: str(uuid4()),
        index=True,
        readonly=True,
    )
    generation = fields.Integer(default=1, readonly=True)
    external_task_id = fields.Char(index=True, readonly=True)
    external_status = fields.Char(readonly=True)
    webhook_token = fields.Char(
        required=True,
        default=lambda self: secrets.token_urlsafe(32),
        copy=False,
        index=True,
        help="High-entropy callback token. Providers should additionally sign webhooks.",
    )

    progress = fields.Float(default=0.0, readonly=True)
    attempt_count = fields.Integer(default=0, readonly=True)
    poll_count = fields.Integer(default=0, readonly=True)
    max_poll_count = fields.Integer(
        default=0,
        help="Maximum poll attempts. Zero means unlimited until timeout.",
    )
    poll_interval = fields.Integer(
        default=30,
        help="Default delay in seconds between remote status checks.",
    )
    submitted_at = fields.Datetime(readonly=True)
    started_at = fields.Datetime(readonly=True)
    completed_at = fields.Datetime(readonly=True)
    next_poll_at = fields.Datetime(readonly=True)
    timeout_at = fields.Datetime(
        help="Optional absolute deadline for this business task."
    )

    resource_model = fields.Char(index=True)
    resource_id = fields.Many2oneReference(model_field="resource_model")
    resource_version = fields.Char(
        help="Checksum or version used by handlers to reject stale results."
    )
    input_payload = fields.Json(default=dict)
    output_payload = fields.Json(default=dict, readonly=True)
    adapter_metadata = fields.Json(default=dict, readonly=True)
    error_type = fields.Char(readonly=True)
    error_message = fields.Text(readonly=True)

    item_ids = fields.One2many("async.task.item", "task_id", string="Items")
    event_ids = fields.One2many("async.task.event", "task_id", string="Webhook Events")
    dependency_ids = fields.Many2many(
        "async.task",
        "async_task_dependency_rel",
        "task_id",
        "dependency_id",
        string="Dependencies",
    )
    dependent_ids = fields.Many2many(
        "async.task",
        "async_task_dependency_rel",
        "dependency_id",
        "task_id",
        string="Dependent Tasks",
        readonly=True,
    )

    _idempotency_unique = models.Constraint(
        "UNIQUE(idempotency_key)",
        "The asynchronous task idempotency key must be unique.",
    )
    _webhook_token_unique = models.Constraint(
        "UNIQUE(webhook_token)",
        "The asynchronous task webhook token must be unique.",
    )
    _progress_range = models.Constraint(
        "CHECK(progress >= 0 AND progress <= 100)",
        "Task progress must be between 0 and 100.",
    )
    _poll_values_valid = models.Constraint(
        "CHECK(poll_interval > 0 AND max_poll_count >= 0)",
        "Poll interval must be positive and maximum poll count cannot be negative.",
    )
    _state_poll_idx = models.Index("(state, next_poll_at)")
    _adapter_external_idx = models.Index(
        "(adapter_usage, external_task_id) WHERE external_task_id IS NOT NULL"
    )

    @api.model_create_multi
    def create(self, vals_list):
        if not self.env.su:
            forbidden = ENGINE_FIELDS - {"state"}
            for vals in vals_list:
                if vals.get("state", "draft") != "draft" or forbidden & vals.keys():
                    raise AccessError(
                        _("Execution state can only be initialized by the task engine.")
                    )
                vals.pop("state", None)
                vals.pop("generation", None)
                vals.pop("webhook_token", None)
        for vals in vals_list:
            vals.setdefault("name", vals.get("task_type") or _("Asynchronous Task"))
        return super().create(vals_list)

    def write(self, vals):
        if not self.env.su:
            if ENGINE_FIELDS & vals.keys():
                raise AccessError(
                    _("Execution fields can only be changed by the task engine.")
                )
            if CONFIG_FIELDS & vals.keys() and any(task.state != "draft" for task in self):
                raise UserError(_("Task configuration can only be changed in draft state."))
        return super().write(vals)

    @api.constrains("dependency_ids")
    def _check_dependency_cycles(self):
        for task in self:
            frontier = task.dependency_ids
            seen = self.env["async.task"]
            while frontier:
                if task in frontier:
                    raise ValidationError(
                        _("An asynchronous task cannot depend on itself.")
                    )
                seen |= frontier
                frontier = frontier.mapped("dependency_ids") - seen

    @contextmanager
    def work_on(self, model_name=None, **kwargs):
        self.ensure_one()
        kwargs.setdefault("task", self)
        with super().work_on(model_name or self._name, **kwargs) as work:
            yield work

    def _resolve_component(self, usage):
        self.ensure_one()
        if not usage:
            raise UserError(_("No component usage is configured for this task."))
        try:
            with self.work_on(self._name) as work:
                return work.component(usage=usage)
        except (NoComponentError, RegistryNotReadyError) as exc:
            raise UserError(
                _(
                    "No component is registered for async task usage '%(usage)s'.",
                    usage=usage,
                )
            ) from exc

    @api.model
    def _terminal_states(self):
        return TERMINAL_STATES

    def _execution_record(self):
        """Return this task in its owner's isolated company context."""
        self.ensure_one()
        return (
            self.with_user(self.user_id)
            .with_company(self.company_id)
            .with_context(allowed_company_ids=[self.company_id.id])
        )

    def _engine_write(self, values):
        self.ensure_one()
        self.sudo().write(values)
        self.invalidate_recordset()
        return self

    def _lock_for_update(self):
        self.ensure_one()
        self.env.cr.execute(
            "SELECT id FROM async_task WHERE id = %s FOR UPDATE",
            [self.id],
        )
        self.invalidate_recordset()
        return self

    def _transition(self, new_state, **values):
        self.ensure_one()
        if new_state != self.state and new_state not in ALLOWED_TRANSITIONS[self.state]:
            raise ValidationError(
                _(
                    "Invalid asynchronous task transition: %(source)s → %(target)s",
                    source=self.state,
                    target=new_state,
                )
            )
        values["state"] = new_state
        return self._engine_write(values)

    def _deadline_reached(self):
        self.ensure_one()
        return bool(self.timeout_at and fields.Datetime.now() >= self.timeout_at)

    def _pending_items(self):
        self.ensure_one()
        return self.item_ids.filtered(lambda item: item.state != "succeeded")

    def _require_manager(self):
        if not self.env.su and not self.env.user.has_group(
            "async_task.group_async_task_manager"
        ):
            raise AccessError(_("Only Async Task managers can submit or retry tasks."))

    def action_queue(self):
        self._require_manager()
        for task in self:
            task._lock_for_update()
            if task.state not in {"draft", "blocked", "waiting_dependencies"}:
                raise UserError(
                    _("Only draft, blocked, or dependency-waiting tasks can be queued.")
                )
            task._evaluate_dependencies(queue_ready=True)
        return True

    def _evaluate_dependencies(self, queue_ready=False):
        self.ensure_one()
        dependencies = self.dependency_ids
        if dependencies.filtered(lambda dependency: dependency.state not in TERMINAL_STATES):
            if self.state != "waiting_dependencies":
                self._transition("waiting_dependencies")
            return False

        if (
            dependencies
            and self.dependency_policy == "all_succeeded"
            and any(dependency.state not in SUCCESS_STATES for dependency in dependencies)
        ):
            if self.state != "blocked":
                self._transition(
                    "blocked",
                    error_type="dependency",
                    error_message=_("One or more required tasks did not succeed."),
                    completed_at=fields.Datetime.now(),
                )
                self._release_dependents()
            return False

        if queue_ready:
            self._transition(
                "queued",
                error_type=False,
                error_message=False,
                completed_at=False,
            )
            self._enqueue_submit()
        return True

    def _enqueue_submit(self):
        self.ensure_one()
        task = self._execution_record()
        return task.with_delay(
            priority=task.priority,
            max_retries=0,
            channel=task.queue_channel,
            description=_("Submit async task %s", task.display_name),
            identity_key=f"async-task-submit-{task.id}-{task.generation}",
        )._job_submit(task.generation)

    def _enqueue_poll(self, retry_after=None, manual=False):
        self.ensure_one()
        delay = max(1, int(retry_after or self.poll_interval))
        self._engine_write(
            {"next_poll_at": fields.Datetime.now() + timedelta(seconds=delay)}
        )
        task = self._execution_record()
        suffix = f"manual-{uuid4()}" if manual else str(task.generation)
        return task.with_delay(
            priority=task.priority,
            eta=None if manual else delay,
            max_retries=0,
            channel=task.queue_channel,
            description=_("Poll async task %s", task.display_name),
            identity_key=f"async-task-poll-{task.id}-{suffix}",
        )._job_poll(task.generation)

    def action_poll_now(self):
        self._require_manager()
        for task in self:
            task._lock_for_update()
            if task.state not in {"waiting", "cancel_pending"}:
                raise UserError(_("Only waiting tasks can be polled."))
            task._enqueue_poll(manual=True)
        return True

    def _enqueue_cancel(self):
        self.ensure_one()
        execution_task = self._execution_record()
        return execution_task.with_delay(
            priority=execution_task.priority,
            max_retries=0,
            channel=execution_task.queue_channel,
            description=_("Cancel async task %s", execution_task.display_name),
            identity_key=(
                f"async-task-cancel-{execution_task.id}-"
                f"{execution_task.generation}"
            ),
        )._job_cancel(execution_task.generation)

    def action_cancel(self):
        for task in self:
            task._lock_for_update()
            if task.state in {"succeeded", "partially_succeeded", "cancelled"}:
                continue
            if task.state in {
                "draft",
                "waiting_dependencies",
                "queued",
                "blocked",
                "failed",
                "expired",
            }:
                task._transition(
                    "cancelled",
                    completed_at=fields.Datetime.now(),
                    next_poll_at=False,
                )
                task._resolve_component(task.handler_usage).on_cancelled(task)
                task._release_dependents()
                continue
            submit_in_flight = task.state == "submitting"
            task._transition("cancel_pending")
            if not submit_in_flight:
                task._enqueue_cancel()
        return True

    def action_retry(self):
        self._require_manager()
        for task in self:
            task._lock_for_update()
            if task.state not in {
                "failed",
                "partially_succeeded",
                "blocked",
                "cancelled",
                "expired",
            }:
                raise UserError(_("Only terminal unsuccessful tasks can be retried."))
            task.item_ids.filtered(
                lambda item: item.state != "succeeded"
            )._engine_write(
                {
                    "state": "pending",
                    "progress": 0.0,
                    "external_item_id": False,
                    "output_payload": {},
                    "error_message": False,
                    "started_at": False,
                    "completed_at": False,
                }
            )
            task._transition(
                "draft",
                generation=task.generation + 1,
                webhook_token=secrets.token_urlsafe(32),
                wait_mode="none",
                progress=0.0,
                external_task_id=False,
                external_status=False,
                output_payload={},
                adapter_metadata={},
                error_type=False,
                error_message=False,
                submitted_at=False,
                started_at=False,
                completed_at=False,
                next_poll_at=False,
                poll_count=0,
            )
            task._evaluate_dependencies(queue_ready=True)
        return True

    def _job_submit(self, expected_generation=None):
        """Claim a queued task, then delegate remote I/O to a lock-free job."""
        self.ensure_one()
        self._lock_for_update()
        if expected_generation and expected_generation != self.generation:
            return
        if self.state != "queued":
            return
        if self._deadline_reached():
            self._mark_expired(_("The asynchronous task deadline was reached."))
            return

        now = fields.Datetime.now()
        self._transition(
            "submitting",
            started_at=self.started_at or now,
            submitted_at=now,
            attempt_count=self.attempt_count + 1,
            error_type=False,
            error_message=False,
        )
        self._pending_items()._engine_write(
            {
                "state": "running",
                "started_at": now,
                "attempt_count": self.attempt_count,
            }
        )
        task = self._execution_record()
        task.with_delay(
            priority=task.priority,
            max_retries=0,
            channel=task.queue_channel,
            description=_("Execute async task %s", task.display_name),
            identity_key=f"async-task-execute-{task.id}-{task.generation}",
        )._job_execute_submit(task.generation)

    def _job_execute_submit(self, expected_generation):
        """Perform submit I/O without retaining a task row lock."""
        self.ensure_one()
        if expected_generation != self.generation or self.state not in {
            "submitting",
            "cancel_pending",
        }:
            return
        try:
            adapter = self._resolve_component(self.adapter_usage)
            outcome = adapter.submit(self, self._pending_items())
            self._lock_for_update()
            if expected_generation != self.generation or self.state not in {
                "submitting",
                "cancel_pending",
            }:
                return
            with self.env.cr.savepoint():
                self._apply_outcome(outcome)
                if self.state == "cancel_pending":
                    self._enqueue_cancel()
        except RetryableJobError:
            raise
        except Exception as exc:  # noqa: BLE001 - component boundary
            self.invalidate_recordset()
            self._lock_for_update()
            if expected_generation != self.generation or self.state not in {
                "submitting",
                "cancel_pending",
            }:
                return
            _logger.exception("Failed to submit async task %s", self.id)
            self._mark_failed_from_exception(exc)

    def _job_poll(self, expected_generation=None):
        """Claim one poll attempt, then delegate remote I/O to another job."""
        self.ensure_one()
        self._lock_for_update()
        if expected_generation and expected_generation != self.generation:
            return
        if self.state not in {"waiting", "cancel_pending"}:
            return
        if self._deadline_reached():
            self._mark_expired(_("The asynchronous task deadline was reached."))
            return
        if self.max_poll_count and self.poll_count >= self.max_poll_count:
            self._mark_expired(_("The asynchronous task exceeded its poll limit."))
            return

        self._engine_write(
            {"poll_count": self.poll_count + 1, "next_poll_at": False}
        )
        if self.state == "waiting":
            self._transition("running")
        task = self._execution_record()
        task.with_delay(
            priority=task.priority,
            max_retries=0,
            channel=task.queue_channel,
            description=_("Execute poll for async task %s", task.display_name),
            identity_key=(
                f"async-task-execute-poll-{task.id}-{task.generation}-"
                f"{task.poll_count}"
            ),
        )._job_execute_poll(task.generation)

    def _job_execute_poll(self, expected_generation):
        """Perform poll I/O without retaining a task row lock."""
        self.ensure_one()
        if expected_generation != self.generation or self.state not in {
            "running",
            "cancel_pending",
        }:
            return
        try:
            adapter = self._resolve_component(self.adapter_usage)
            outcome = adapter.poll(self)
            self._lock_for_update()
            if expected_generation != self.generation or self.state not in {
                "running",
                "cancel_pending",
            }:
                return
            with self.env.cr.savepoint():
                self._apply_outcome(outcome)
        except RetryableJobError:
            raise
        except Exception as exc:  # noqa: BLE001 - component boundary
            self.invalidate_recordset()
            self._lock_for_update()
            if expected_generation != self.generation or self.state not in {
                "running",
                "cancel_pending",
            }:
                return
            _logger.exception("Failed to poll async task %s", self.id)
            self._mark_failed_from_exception(exc)

    def _job_cancel(self, expected_generation=None):
        """Perform cancellation I/O, taking the row lock only to finalize."""
        self.ensure_one()
        if expected_generation and expected_generation != self.generation:
            return
        if self.state != "cancel_pending":
            return
        if self._deadline_reached():
            self._lock_for_update()
            if self.state == "cancel_pending":
                self._mark_expired(_("The asynchronous task deadline was reached."))
            return
        try:
            adapter = self._resolve_component(self.adapter_usage)
            outcome = adapter.cancel(self)
            self._lock_for_update()
            if expected_generation and expected_generation != self.generation:
                return
            if self.state != "cancel_pending":
                return
            with self.env.cr.savepoint():
                self._apply_outcome(outcome)
        except RetryableJobError:
            raise
        except Exception as exc:  # noqa: BLE001 - component boundary
            self.invalidate_recordset()
            self._lock_for_update()
            if expected_generation and expected_generation != self.generation:
                return
            if self.state != "cancel_pending":
                return
            _logger.exception("Failed to cancel async task %s", self.id)
            self._mark_failed_from_exception(exc)

    def _normalize_outcome(self, outcome):
        if not isinstance(outcome, dict):
            raise ValidationError(_("Async task components must return a dictionary."))
        status = outcome.get("status")
        if status not in {"completed", "waiting", "failed", "cancelled"}:
            raise ValidationError(
                _("Unsupported asynchronous task outcome status: %s", status)
            )
        if status == "waiting" and outcome.get("wait_mode") not in {
            "poll",
            "webhook",
            "manual",
        }:
            raise ValidationError(_("Waiting outcomes require a valid wait mode."))
        progress = outcome.get("progress")
        if progress is not None and not 0 <= float(progress) <= 100:
            raise ValidationError(_("Outcome progress must be between 0 and 100."))
        item_results = outcome.get("item_results") or []
        if not isinstance(item_results, list):
            raise ValidationError(_("Outcome item_results must be a list."))
        return outcome

    def _apply_outcome(self, outcome):
        self.ensure_one()
        outcome = self._normalize_outcome(outcome)
        values = {}
        for source, target in (
            ("external_task_id", "external_task_id"),
            ("external_status", "external_status"),
            ("progress", "progress"),
            ("result", "output_payload"),
            ("metadata", "adapter_metadata"),
        ):
            if source in outcome:
                values[target] = outcome[source]
        if values:
            self._engine_write(values)

        status = outcome["status"]
        item_results = outcome.get("item_results") or []
        if status == "waiting":
            if item_results:
                self._apply_item_results(item_results, terminal=False)
            wait_mode = outcome["wait_mode"]
            if self.state == "cancel_pending":
                self._engine_write({"wait_mode": wait_mode})
            else:
                self._transition("waiting", wait_mode=wait_mode)
            if wait_mode == "poll":
                self._enqueue_poll(outcome.get("retry_after"))
            return

        item_results = outcome.get("item_results") or []
        if item_results:
            reported_keys = self._apply_item_results(item_results)
            missing_items = self._pending_items().filtered(
                lambda item: item.correlation_key not in reported_keys
            )
            missing_items._engine_write(
                {
                    "state": "failed",
                    "completed_at": fields.Datetime.now(),
                    "error_message": _("Provider omitted this item from its result."),
                }
            )
        elif status == "completed":
            self._pending_items()._engine_write(
                {
                    "state": "succeeded",
                    "progress": 100.0,
                    "completed_at": fields.Datetime.now(),
                    "error_message": False,
                }
            )
        elif status == "failed":
            self._pending_items()._engine_write(
                {
                    "state": "failed",
                    "completed_at": fields.Datetime.now(),
                    "error_message": outcome.get("error")
                    or _("Remote task failed."),
                }
            )

        handler = self._resolve_component(self.handler_usage)
        if status == "completed":
            handler.apply_task_result(self, outcome.get("result"))
            succeeded_items = self.item_ids.filtered(
                lambda item: item.state == "succeeded"
            )
            unsuccessful_items = self.item_ids - succeeded_items
            if unsuccessful_items and succeeded_items:
                final_state = "partially_succeeded"
            elif unsuccessful_items:
                final_state = "failed"
            else:
                final_state = "succeeded"
            item_progress = (
                100.0 * len(succeeded_items) / len(self.item_ids)
                if self.item_ids
                else 100.0
            )
            self._transition(
                final_state,
                wait_mode="none",
                progress=item_progress,
                completed_at=fields.Datetime.now(),
                next_poll_at=False,
                error_type="item" if unsuccessful_items else False,
                error_message=(
                    _("One or more task items did not succeed.")
                    if unsuccessful_items
                    else False
                ),
            )
            if final_state in {"succeeded", "partially_succeeded"}:
                handler.on_completed(self)
            else:
                handler.on_failed(self)
        elif status == "failed":
            self._transition(
                "failed",
                wait_mode="none",
                completed_at=fields.Datetime.now(),
                next_poll_at=False,
                error_type=outcome.get("error_type") or "remote",
                error_message=outcome.get("error") or _("Remote task failed."),
            )
            handler.on_failed(self)
        else:
            self.item_ids.filtered(
                lambda item: item.state not in {"succeeded", "failed"}
            )._engine_write(
                {
                    "state": "cancelled",
                    "completed_at": fields.Datetime.now(),
                }
            )
            self._transition(
                "cancelled",
                wait_mode="none",
                completed_at=fields.Datetime.now(),
                next_poll_at=False,
            )
            handler.on_cancelled(self)
        self._release_dependents()

    def _apply_item_results(self, item_results, terminal=True):
        self.ensure_one()
        item_by_key = {item.correlation_key: item for item in self.item_ids}
        handler = self._resolve_component(self.handler_usage)
        now = fields.Datetime.now()
        reported_keys = set()
        allowed_statuses = {"succeeded", "failed", "cancelled"}
        if not terminal:
            allowed_statuses |= {"pending", "running"}
        for item_result in item_results:
            if not isinstance(item_result, dict):
                raise ValidationError(_("Each item result must be a dictionary."))
            key = item_result.get("correlation_key")
            if not key or key in reported_keys:
                raise ValidationError(_("Item result correlation keys must be unique."))
            reported_keys.add(key)
            item = item_by_key.get(key)
            if not item:
                raise ValidationError(
                    _("Unknown asynchronous task item correlation key: %s", key)
                )
            item_status = item_result.get("status", "succeeded")
            if item_status not in allowed_statuses:
                raise ValidationError(
                    _("Unsupported item result status: %s", item_status)
                )
            was_succeeded = item.state == "succeeded"
            if was_succeeded and item_status != "succeeded":
                continue
            values = {
                "state": item_status,
                "error_message": item_result.get("error") or False,
            }
            if "progress" in item_result:
                values["progress"] = item_result["progress"]
            elif item_status == "succeeded":
                values["progress"] = 100.0
            if item_status in {"succeeded", "failed", "cancelled"}:
                values["completed_at"] = now
            if "result" in item_result:
                values["output_payload"] = item_result["result"]
            if "external_item_id" in item_result:
                values["external_item_id"] = item_result["external_item_id"]
            item._engine_write(values)
            if item_status == "succeeded" and not was_succeeded:
                handler.apply_item_result(self, item, item_result.get("result"))
        return reported_keys

    def _mark_failed_from_exception(self, exc):
        self.ensure_one()
        if self.state in TERMINAL_STATES:
            return
        self._transition(
            "failed",
            wait_mode="none",
            completed_at=fields.Datetime.now(),
            next_poll_at=False,
            error_type=type(exc).__name__,
            error_message=str(exc),
        )
        try:
            with self.env.cr.savepoint():
                self._resolve_component(self.handler_usage).on_failed(self)
        except Exception:  # noqa: BLE001 - retain the original task failure
            _logger.exception("Async task failure handler failed for task %s", self.id)
        self._release_dependents()

    def _mark_expired(self, message):
        self.ensure_one()
        self._transition(
            "expired",
            wait_mode="none",
            completed_at=fields.Datetime.now(),
            next_poll_at=False,
            error_type="timeout",
            error_message=message,
        )
        try:
            with self.env.cr.savepoint():
                self._resolve_component(self.handler_usage).on_failed(self)
        except Exception:  # noqa: BLE001 - expiration must remain durable
            _logger.exception("Async task expiration handler failed for task %s", self.id)
        self._release_dependents()

    @api.model
    def _cron_expire_tasks(self, limit=200):
        """Expire overdue non-terminal tasks, including webhook/manual waits."""
        tasks = self.sudo().search(
            [
                ("state", "not in", list(TERMINAL_STATES)),
                ("timeout_at", "!=", False),
                ("timeout_at", "<=", fields.Datetime.now()),
            ],
            order="timeout_at, id",
            limit=limit,
        )
        expired = 0
        for task in tasks:
            with self.env.cr.savepoint():
                execution_task = task._execution_record()
                execution_task._lock_for_update()
                if (
                    execution_task.state not in TERMINAL_STATES
                    and execution_task._deadline_reached()
                ):
                    execution_task._mark_expired(
                        _("The asynchronous task deadline was reached.")
                    )
                    expired += 1
        return expired

    def _release_dependents(self):
        self.ensure_one()
        for dependent in self.sudo().dependent_ids:
            if dependent.state not in {"draft", "waiting_dependencies", "blocked"}:
                continue
            execution_dependent = dependent._execution_record()
            execution_dependent._lock_for_update()
            execution_dependent._evaluate_dependencies(queue_ready=True)
