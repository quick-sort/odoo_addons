"""Business result handlers for asynchronous tasks."""

from odoo.addons.component.core import AbstractComponent, Component


class AsyncTaskHandler(AbstractComponent):
    """Apply transport-neutral task outcomes to business records.

    Adapters only communicate with an external backend.  Handlers own the
    business mapping, which lets the same operation engine serve unrelated
    domains without depending on any of them.
    """

    _name = "async.task.handler"
    _collection = "async.task"

    def _not_implemented(self, method):
        raise NotImplementedError(
            f"Async task handler '{self._usage}' ({self._name}) does not "
            f"implement {method}()"
        )

    def apply_item_result(self, task, item, result):
        """Apply one successful item result to its business resource."""
        return self._not_implemented("apply_item_result")

    def apply_task_result(self, task, result):
        """Apply the task-level result after item results are persisted."""
        return self._not_implemented("apply_task_result")

    def on_completed(self, task):
        """Run after the task reached a successful terminal state."""
        return self._not_implemented("on_completed")

    def on_failed(self, task):
        """Run after the task reached a failed or expired state."""
        return self._not_implemented("on_failed")

    def on_cancelled(self, task):
        """Run after the task reached the cancelled state."""
        return self._not_implemented("on_cancelled")


class NoopAsyncTaskHandler(Component):
    """Default handler for tasks whose adapter result is self-contained."""

    _name = "async.task.handler.noop"
    _inherit = "async.task.handler"
    _usage = "async_task.handler.noop"

    def apply_item_result(self, task, item, result):
        return None

    def apply_task_result(self, task, result):
        return None

    def on_completed(self, task):
        return None

    def on_failed(self, task):
        return None

    def on_cancelled(self, task):
        return None
