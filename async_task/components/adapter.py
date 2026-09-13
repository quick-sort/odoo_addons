"""Component contract for asynchronous task backends."""

from odoo.addons.component.core import AbstractComponent


class AsyncTaskAdapter(AbstractComponent):
    """Transport-neutral contract implemented by task backend addons.

    Implementations return a plain dictionary outcome.  ``submit()``,
    ``poll()``, ``cancel()``, and ``parse_webhook()`` all use the same shape::

        {
            "status": "completed" | "waiting" | "failed" | "cancelled",
            "wait_mode": "poll" | "webhook" | "manual",  # when waiting
            "external_task_id": "...",
            "retry_after": 30,                              # seconds
            "progress": 42.0,                              # 0..100
            "result": {...},
            "item_results": [
                {
                    "correlation_key": "...",
                    "status": "pending" | "running" | "succeeded" |
                              "failed" | "cancelled",
                    "result": {...},
                    "error": "...",
                    "external_item_id": "...",
                }
            ],
            "metadata": {...},
            "error": "...",
        }

    A blocking API returns ``completed`` from ``submit``.  A remote task API
    returns ``waiting`` and is resumed by polling or a webhook.  This keeps
    execution mode out of the task engine and out of business callers.
    """

    _name = "async.task.adapter"
    _collection = "async.task"

    def _not_implemented(self, method):
        raise NotImplementedError(
            f"Async task adapter '{self._usage}' ({self._name}) does not "
            f"implement {method}()"
        )

    def submit(self, task, items):
        """Start the operation and return a normalized outcome dictionary."""
        return self._not_implemented("submit")

    def poll(self, task):
        """Read the state of a previously submitted remote operation."""
        return self._not_implemented("poll")

    def cancel(self, task):
        """Request cancellation and return a normalized outcome dictionary."""
        return self._not_implemented("cancel")

    def verify_webhook(self, task, headers, raw_body):
        """Verify webhook authenticity before any event is persisted."""
        return self._not_implemented("verify_webhook")

    def webhook_event_key(self, task, headers, raw_body):
        """Return the provider event ID, or ``None`` to use a body digest."""
        return None

    def parse_webhook(self, task, headers, raw_body):
        """Convert a verified webhook body to a normalized outcome."""
        return self._not_implemented("parse_webhook")
