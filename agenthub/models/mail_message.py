from odoo import fields, models


class MailMessage(models.Model):
    """Transport bookkeeping fields for messages carried by agenthub.

    Content lives in the standard ``mail.message`` columns (``body``,
    ``author_id``, attachments); these fields carry the channel-side identity
    and the outbound delivery state machine. The ``agenthub_delivery_state``
    column doubles as the cross-process outbound queue: the gevent worker polls
    ``pending`` messages for its channel and marks them ``sent`` / ``failed``.
    """

    _inherit = "mail.message"

    agenthub_role = fields.Char(
        string="Agent Hub Role",
        help="Who produced this message: 'user' (Odoo side) or 'assistant' (the external agent).",
    )
    agenthub_direction = fields.Selection(
        [("in", "Inbound"), ("out", "Outbound")],
        string="Agent Hub Direction",
    )
    agenthub_content = fields.Text(
        string="Agent Hub Raw Content",
        help="Raw channel-side content, before HTML rendering. Agents read this "
        "to interpret the message (e.g. OpenClaw's <think> blocks).",
    )
    agenthub_external_id = fields.Char(
        string="Agent Hub External ID", index=True
    )
    agenthub_reply_to_external_id = fields.Char(
        string="Agent Hub Reply-To External ID", index=True
    )
    agenthub_delivery_state = fields.Selection(
        [("pending", "Pending"), ("sent", "Sent"), ("failed", "Failed")],
        string="Agent Hub Delivery State",
        index=True,
    )
    agenthub_stream_id = fields.Char(
        string="Agent Hub Stream ID",
        index=True,
        help="Correlates the frames of one streamed reply.",
    )
