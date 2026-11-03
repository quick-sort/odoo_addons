import logging

import requests

from odoo import _, api, fields, models

_logger = logging.getLogger(__name__)


class AgenthubRecordCursor(models.Model):
    """Checkpoint for the Odoo recorder pulling the relay record feed."""

    _name = "agenthub.record.cursor"
    _description = "Agent Hub Record Cursor"
    _order = "id"

    key = fields.Char(required=True, default="default", index=True)
    cursor = fields.Char()
    last_event_at = fields.Datetime()
    lag_seconds = fields.Float()

    _record_cursor_uniq = models.Constraint(
        "UNIQUE(key)",
        "Record cursor key must be unique.",
    )

    @api.model
    def _get(self, key="default"):
        record = self.search([("key", "=", key)], limit=1)
        return record or self.create({"key": key})

    @api.model
    def _set(self, cursor, key="default", last_event_at=None, lag_seconds=None):
        record = self._get(key)
        vals = {"cursor": cursor}
        if last_event_at is not None:
            vals["last_event_at"] = last_event_at
        if lag_seconds is not None:
            vals["lag_seconds"] = lag_seconds
        record.write(vals)
        return record

    @api.model
    def _relay_config(self):
        params = self.env["ir.config_parameter"].sudo()
        url = params.get_param("agenthub.relay_url")
        token = params.get_param("agenthub.relay_recorder_token")
        limit = int(params.get_param("agenthub.recorder_batch_limit") or 500)
        return url, token, max(1, min(limit, 1000))

    @api.model
    def _pull_once(self):
        url, token, limit = self._relay_config()
        if not url or not token:
            return 0
        record = self._get("relay")
        try:
            cursor = int(record.cursor or 0)
        except (TypeError, ValueError):
            cursor = 0
        headers = {"X-AgentHub-Recorder-Token": token}
        try:
            response = requests.get(
                url.rstrip("/") + "/v1/record",
                params={"cursor": cursor, "limit": limit},
                headers=headers,
                timeout=10,
            )
            response.raise_for_status()
            data = response.json()
        except Exception:  # noqa: BLE001 - HTTP boundary
            _logger.exception("agenthub recorder: could not fetch record feed")
            return 0
        events = data.get("events") or []
        recorder = self.env["agenthub.recorder"]
        for event in events:
            recorder._process_event(event)
        next_cursor = int(data.get("next_cursor", cursor))
        if next_cursor != cursor:
            record._set(
                str(next_cursor),
                key="relay",
                last_event_at=fields.Datetime.now(),
                lag_seconds=float(data.get("lag_seconds") or 0),
            )
            try:
                requests.post(
                    url.rstrip("/") + "/v1/record/ack",
                    json={"cursor": next_cursor},
                    headers=headers,
                    timeout=10,
                )
            except Exception:  # noqa: BLE001 - ack is advisory
                _logger.exception("agenthub recorder: record ack failed")
        return len(events)

    @api.model
    def _cron_pull(self):
        return self._pull_once()
