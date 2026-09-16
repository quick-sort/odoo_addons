import logging

from odoo import api, fields, models

_logger = logging.getLogger(__name__)


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
        [("new", "New"), ("processed", "Processed"), ("error", "Error")],
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
        """Turn an inbound email into a relay record, then into an item.

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

    def _to_item(self):
        """Hand the email to its channel for ingestion into the pool."""
        self.ensure_one()
        if not self.channel_id:
            self.state = "error"
            self.error_message = "No channel matched the receiving address."
            return

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
                        "message_id": self.message_ids[:1].message_id or "",
                    }
                ]
            )
            self.state = "processed"
        except Exception as exc:  # noqa: BLE001 — recorded on the relay record
            self.state = "error"
            self.error_message = str(exc)
            _logger.exception("infohub email: could not ingest message %s", self.id)

    def action_reprocess(self):
        """Re-run ingestion — useful after fixing a channel's configuration."""
        for message in self:
            message._to_item()
        return True
