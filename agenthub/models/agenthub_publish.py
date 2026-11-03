import hashlib
import hmac
import json
import logging
import time
import uuid
from datetime import datetime, timedelta, timezone

import requests

from odoo import SUPERUSER_ID, _, api, fields, models
from odoo.sql_db import db_connect

_logger = logging.getLogger(__name__)


class PublishError(Exception):
    """A relay publish failure with an explicit retry decision."""

    def __init__(self, message, retryable=True):
        super().__init__(message)
        self.retryable = retryable


class AgenthubPublish(models.Model):
    """Odoo -> relay publish outbox.

    Events are written in the same transaction as the business message/command,
    then pushed by a cron worker. The relay deduplicates by ``event_id``.
    """

    _name = "agenthub.publish"
    _description = "Agent Hub Publish Outbox"
    _order = "id asc"

    MAX_ATTEMPTS = 10

    event_id = fields.Char(required=True, index=True)
    event_type = fields.Char(required=True)
    event_version = fields.Integer(default=1, required=True)
    envelope = fields.Json(required=True)
    state = fields.Selection(
        [
            ("pending", "Pending"),
            ("sending", "Sending"),
            ("sent", "Sent"),
            ("failed", "Failed"),
            ("dead", "Dead"),
        ],
        default="pending",
        required=True,
        index=True,
    )
    attempt = fields.Integer(default=0)
    next_retry = fields.Datetime()
    last_error = fields.Text()
    sent_at = fields.Datetime()

    _publish_event_uniq = models.Constraint(
        "UNIQUE(event_id)",
        "Event id must be unique.",
    )

    @api.model
    def _enqueue(
        self,
        event_type,
        payload,
        event_id=None,
        route=None,
        turn=None,
        meta=None,
        event_version=1,
    ):
        """Create an outbox event, or return the existing one."""
        event_id = event_id or str(uuid.uuid4())
        existing = self.search([("event_id", "=", event_id)], limit=1)
        if existing:
            return existing
        envelope = {
            "event_version": event_version,
            "event_id": event_id,
            "event_type": event_type,
            "occurred_at": datetime.now(timezone.utc).isoformat(),
            "source": {"type": "odoo", "id": self.env.cr.dbname},
            "route": route or {},
            "turn": turn or {},
            "payload": payload,
            "meta": meta or {},
        }
        record = self.create(
            {
                "event_id": event_id,
                "event_type": event_type,
                "event_version": event_version,
                "envelope": envelope,
            }
        )
        record._schedule_send()
        return record

    def _schedule_send(self):
        """Try to push right after commit; the cron remains the retry path."""
        self.ensure_one()
        params = self.env["ir.config_parameter"].sudo()
        if not params.get_param("agenthub.relay_url") or not params.get_param(
            "agenthub.relay_secret"
        ):
            return
        publish_id = self.id
        dbname = self.env.cr.dbname

        def _send_after_commit():
            with db_connect(dbname).cursor() as cr:
                env = api.Environment(cr, SUPERUSER_ID, {})
                record = env["agenthub.publish"].browse(publish_id)
                if record.exists():
                    record._send()

        self.env.cr.postcommit.add(_send_after_commit)

    @api.model
    def _cron_process(self, limit=100):
        return self._process_pending(limit=limit)

    @api.model
    def _process_pending(self, limit=50):
        now = fields.Datetime.now()
        events = self.search(
            [
                ("state", "in", ("pending", "failed")),
                "|",
                ("next_retry", "=", False),
                ("next_retry", "<=", now),
            ],
            order="id asc",
            limit=limit,
        )
        for event in events:
            event._send()
        return len(events)

    def _send(self):
        self.ensure_one()
        self.write({"state": "sending"})
        try:
            result = self._send_envelope(self.envelope)
        except PublishError as exc:
            self._mark_failed(str(exc), retry=exc.retryable)
            return False
        except Exception as exc:  # noqa: BLE001 - HTTP boundary
            self._mark_failed(str(exc), retry=True)
            return False
        if result is True:
            self.write(
                {
                    "state": "sent",
                    "sent_at": fields.Datetime.now(),
                    "last_error": False,
                    "next_retry": False,
                }
            )
            return True
        self._mark_failed(_("Relay is not configured."), retry=True)
        return False

    def _send_envelope(self, envelope):
        """POST one envelope to the relay.

        Returns ``True`` on success (including duplicate), ``None`` when the
        relay is not configured, and raises for retryable/terminal HTTP errors.
        """
        self.ensure_one()
        params = self.env["ir.config_parameter"].sudo()
        url = params.get_param("agenthub.relay_url")
        secret = params.get_param("agenthub.relay_secret")
        if not url or not secret:
            return None
        body = json.dumps(envelope, separators=(",", ":"), sort_keys=True)
        timestamp = str(int(time.time()))
        signature = hmac.new(
            secret.encode(),
            f"{timestamp}.{body}".encode(),
            hashlib.sha256,
        ).hexdigest()
        response = requests.post(
            url.rstrip("/") + "/v1/publish",
            data=body.encode(),
            headers={
                "Content-Type": "application/json",
                "X-AgentHub-Timestamp": timestamp,
                "X-AgentHub-Signature": signature,
            },
            timeout=10,
        )
        if response.status_code in (200, 201, 409):
            return True
        if response.status_code == 429 or 500 <= response.status_code < 600:
            raise PublishError(
                _("Relay temporarily unavailable (HTTP %s).")
                % response.status_code,
                retryable=True,
            )
        raise PublishError(
            _("Relay rejected event: HTTP %s %s")
            % (response.status_code, response.text[:200]),
            retryable=False,
        )

    def _mark_failed(self, error, retry=True):
        self.ensure_one()
        attempt = self.attempt + 1
        if retry and attempt < self.MAX_ATTEMPTS:
            delay = min(300, 2**attempt)
            self.write(
                {
                    "state": "failed",
                    "attempt": attempt,
                    "last_error": error,
                    "next_retry": fields.Datetime.now()
                    + timedelta(seconds=delay),
                }
            )
        else:
            self.write(
                {
                    "state": "dead",
                    "attempt": attempt,
                    "last_error": error,
                    "next_retry": False,
                }
            )
