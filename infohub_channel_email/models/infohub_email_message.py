import json
import logging

from odoo import _, api, fields, models
from odoo.tools import html2plaintext, html_escape

_logger = logging.getLogger(__name__)

SPLITTER_CODE = "infohub_email_splitter"


class InfohubEmailMessage(models.Model):
    """Relay that receives inbound newsletter email.

    ``mail.alias`` can only route to a model that inherits ``mail.thread`` (its
    ``alias_model_id`` domain requires a ``message_ids`` field), so the mail
    cannot be delivered straight into ``infohub.item``. Routing it through this
    relay instead keeps the pool free of chatter tables: ``mail_message``,
    ``mail_followers`` and ``mail_notification`` grow with this model, not with
    the number of news items.

    It also keeps the original email around, which is what you want when a
    newsletter's layout changes and the parsing needs revisiting.
    """

    _name = "infohub.email.message"
    _inherit = ["mail.thread"]
    _description = "InfoHub Inbound Email"
    _order = "date desc, id desc"

    subject = fields.Char()
    email_from = fields.Char()
    date = fields.Datetime()
    body = fields.Html(sanitize=True)

    channel_id = fields.Many2one(
        "infohub.channel",
        ondelete="set null",
        index=True,
        help="Channel matched from the receiving address.",
    )
    item_id = fields.Many2one(
        "infohub.item", ondelete="set null", help="Item this email produced."
    )
    state = fields.Selection(
        [
            ("new", "New"),
            ("queued", "Queued"),
            ("processed", "Processed"),
            ("error", "Error"),
        ],
        default="new",
        required=True,
        index=True,
    )
    error_message = fields.Text()

    # ------------------------------------------------------------------
    # mail.thread hooks
    # ------------------------------------------------------------------

    @api.model
    def message_new(self, msg_dict, custom_values=None):
        """Turn an inbound email into a relay record, then into item(s).

        The alias is static, so the channel is resolved here from the address
        the mail was sent to.
        """
        recipients = " ".join(
            str(msg_dict.get(key) or "")
            for key in ("to", "recipients", "cc")
        ).lower()

        channel = self._match_channel(recipients)
        if not channel:
            _logger.warning(
                "infohub email: no email channel matches recipients %r", recipients
            )

        vals = {
            "subject": msg_dict.get("subject") or "",
            "email_from": msg_dict.get("email_from") or "",
            "date": msg_dict.get("date"),
            "body": msg_dict.get("body") or "",
            "channel_id": channel.id if channel else False,
            "state": "new",
        }
        if custom_values:
            vals.update(custom_values)

        record = super().message_new(msg_dict, custom_values=vals)
        record._to_item()
        return record

    @api.model
    def _match_channel(self, recipients):
        """Find the email channel whose receiving address appears in the mail."""
        if not recipients:
            return self.env["infohub.channel"]
        channels = self.env["infohub.channel"].search(
            [("channel_type", "=", "email"), ("email_to", "!=", False)]
        )
        for channel in channels:
            if channel.email_to and channel.email_to.lower() in recipients:
                return channel
        return self.env["infohub.channel"]

    # ------------------------------------------------------------------
    # Ingestion
    # ------------------------------------------------------------------

    def _to_item(self):
        """Dispatch the email to single-item or split ingestion.

        Digest channels that opt into splitting and have a configured splitter
        agent hand off to a queue job (the LLM call must not block the mail
        gateway); every other case stays the synchronous single-item path.
        """
        self.ensure_one()
        if not self.channel_id:
            self.state = "error"
            self.error_message = "No channel matched the receiving address."
            return

        if self._should_split():
            self.state = "queued"
            self.with_delay(
                channel="root.infohub",
                description=_("InfoHub: split %s") % (self.subject or self.id),
                identity_key=f"infohub-email-split-{self.id}",
            )._job_split_and_ingest()
            return

        self._ingest_single()

    def _should_split(self):
        """True when the channel opts in and the splitter agent is runnable."""
        self.ensure_one()
        if not (self.channel_id and self.channel_id.split_items):
            return False
        agent = self.env["llm.agent"].sudo().search([("code", "=", SPLITTER_CODE)])
        return len(agent) == 1 and agent.active and agent.provider_id and agent.model_id

    def _ingest_single(self):
        """Store the whole email as one item (the pre-splitter behaviour)."""
        self.ensure_one()
        try:
            raw_data = {
                "subject": self.subject or "",
                "email_from": self.email_from or "",
                "date": str(self.date or ""),
                "body": self.body or "",
            }
            self.channel_id._ingest(
                [
                    {
                        "title": self.subject or "",
                        "url": "",
                        "raw_data": raw_data,
                        "external_id": self._message_id(),
                    }
                ]
            )
            self.state = "processed"
        except Exception as exc:  # noqa: BLE001 — recorded on the relay record
            self.state = "error"
            self.error_message = str(exc)
            _logger.exception("infohub email: could not ingest message %s", self.id)

    def _job_split_and_ingest(self):
        """Queue-job entry point: split one digest email into item(s)."""
        self.ensure_one()

        # The config may have changed between enqueue and run; degrade to the
        # single-item path rather than dropping the email.
        if not (self.channel_id and self.channel_id.split_items):
            self._ingest_single()
            return
        agent = self.env["llm.agent"].sudo().search([("code", "=", SPLITTER_CODE)])
        if not (len(agent) == 1 and agent.active and agent.provider_id and agent.model_id):
            self._ingest_single()
            return

        body_text = html2plaintext(self.body or "")
        result = agent.invoke(body_text, new_cursor=False)
        if result.get("error"):
            self.state = "error"
            self.error_message = result["error"]
            return

        try:
            items = self._parse_split_response(result.get("result") or "")
        except ValueError as exc:
            self.state = "error"
            self.error_message = str(exc)
            return

        if not items:
            self._ingest_single()
            return

        entries = [self._split_entry(item, i) for i, item in enumerate(items)]
        self.channel_id._ingest(entries)
        self.state = "processed"

    @api.model
    def _parse_split_response(self, raw):
        """Extract a list of ``{title, summary, url}`` from the model's answer.

        Raises ``ValueError`` when no JSON object can be recovered. Entries
        without a title are dropped.
        """
        text = (raw or "").strip()
        if text.startswith("<"):
            text = html2plaintext(text)
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end <= start:
            raise ValueError(_("No JSON object found in the splitter answer."))
        try:
            payload = json.loads(text[start : end + 1])
        except json.JSONDecodeError as exc:
            raise ValueError(_("Invalid JSON in the splitter answer: %s") % exc) from exc

        entries = payload.get("items") if isinstance(payload, dict) else payload
        if not isinstance(entries, list):
            raise ValueError(_("Splitter answer is not a list of items."))

        items = []
        for entry in entries:
            if not isinstance(entry, dict):
                continue
            title = str(entry.get("title") or "").strip()
            if not title:
                continue
            items.append(
                {
                    "title": title,
                    "summary": str(entry.get("summary") or "").strip(),
                    "url": str(entry.get("url") or "").strip(),
                }
            )
        return items

    def _split_entry(self, item, index):
        """Shape one split item into an ``_ingest`` entry.

        ``external_id`` is ``<message-id>#<index>`` so re-processing the same
        email deduplicates against the ``(channel, external_id)`` constraint
        instead of creating duplicates.
        """
        self.ensure_one()
        summary = (item.get("summary") or "").strip()
        return {
            "title": (item.get("title") or "").strip()[:255],
            "url": (item.get("url") or "").strip(),
            "content": self._html_from_text(summary),
            "raw_data": {
                "subject": (item.get("title") or "").strip(),
                "email_from": self.email_from or "",
                "date": str(self.date or ""),
                "body": summary,
            },
            "external_id": f"{self._message_id()}#{index}",
        }

    def _message_id(self):
        """Stable per-email identity used to build item external ids."""
        self.ensure_one()
        return self.message_ids[:1].message_id or f"email-{self.id}"

    @staticmethod
    def _html_from_text(text):
        """Escaped HTML with paragraph breaks, mirroring the channel renderer."""
        return "".join(
            f"<p>{html_escape(block)}</p>"
            for block in (text or "").split("\n\n")
            if block.strip()
        )

    def action_reprocess(self):
        """Re-run ingestion — useful after fixing a channel's configuration."""
        for message in self:
            message._to_item()
        return True
