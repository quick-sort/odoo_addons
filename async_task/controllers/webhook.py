"""Public webhook ingress for provider-native asynchronous tasks."""

import base64
import hashlib
import logging
from http import HTTPStatus

from odoo import http
from odoo.http import request

_logger = logging.getLogger(__name__)

MAX_WEBHOOK_BODY_BYTES = 2 * 1024 * 1024
SENSITIVE_HEADERS = {"authorization", "cookie", "proxy-authorization", "set-cookie"}
WEBHOOK_TASK_STATES = {"submitting", "running", "waiting", "cancel_pending"}


class AsyncTaskWebhookController(http.Controller):
    @http.route(
        "/async-task/webhook/<string:token>",
        type="http",
        auth="public",
        methods=["POST"],
        csrf=False,
        save_session=False,
    )
    def receive(self, token):
        content_length = request.httprequest.content_length
        if content_length is not None and content_length > MAX_WEBHOOK_BODY_BYTES:
            return http.Response(status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE)
        raw_body = request.httprequest.stream.read(MAX_WEBHOOK_BODY_BYTES + 1)
        if len(raw_body) > MAX_WEBHOOK_BODY_BYTES:
            return http.Response(status=HTTPStatus.REQUEST_ENTITY_TOO_LARGE)

        task = (
            request.env["async.task"]
            .sudo()
            .search([("webhook_token", "=", token)], limit=1)
        )
        if not task:
            return http.Response(status=HTTPStatus.NOT_FOUND)

        task._lock_for_update()
        if task.state in task._terminal_states():
            return http.Response(status=HTTPStatus.OK)
        if task.state not in WEBHOOK_TASK_STATES:
            return http.Response(status=HTTPStatus.CONFLICT)

        execution_task = task._execution_record()
        headers = {
            str(key): str(value)
            for key, value in request.httprequest.headers
            if str(key).lower() not in SENSITIVE_HEADERS
        }
        verification_headers = {
            str(key): str(value) for key, value in request.httprequest.headers
        }
        try:
            adapter = execution_task._resolve_component(
                execution_task.adapter_usage
            )
            if not adapter.verify_webhook(
                execution_task, verification_headers, raw_body
            ):
                return http.Response(status=HTTPStatus.UNAUTHORIZED)
            event_key = adapter.webhook_event_key(
                execution_task, verification_headers, raw_body
            )
        except Exception:  # noqa: BLE001 - never expose verifier details publicly
            _logger.exception("Async task webhook verification failed")
            return http.Response(status=HTTPStatus.UNAUTHORIZED)

        event_key = event_key or hashlib.sha256(raw_body).hexdigest()
        event_model = request.env["async.task.event"].sudo()
        event_domain = [
            ("task_id", "=", task.id),
            ("task_generation", "=", task.generation),
            ("event_key", "=", event_key),
        ]
        event = event_model.search(event_domain, limit=1)
        if event:
            return http.Response(status=HTTPStatus.OK)

        event = event_model.create(
            {
                "task_id": task.id,
                "task_generation": task.generation,
                "event_key": event_key,
                "headers": headers,
                "raw_body": base64.b64encode(raw_body),
            }
        )
        event._enqueue()
        return http.Response(status=HTTPStatus.ACCEPTED)
