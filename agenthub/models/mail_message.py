from odoo import api, fields, models


class MailMessage(models.Model):
    """Transport and conversation fields for messages carried by agenthub.

    Content lives in the standard ``mail.message`` columns (``body``,
    ``author_id``, attachments). The ``agenthub_*`` fields carry the semantic
    role, structured tool data, and correlation ids. The hot delivery queue is
    in the relay; the legacy ``agenthub_delivery_state`` field is kept only for
    compatibility/audit.
    """

    _inherit = "mail.message"

    AGENTHUB_XMLIDS = (
        "agenthub.mt_user",
        "agenthub.mt_assistant",
        "agenthub.mt_tool",
        "agenthub.mt_system",
    )

    agenthub_role = fields.Char(
        string="Agent Hub Role",
        help="Who produced this message: 'user', 'assistant', 'tool', or 'system'.",
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
    agenthub_body_json = fields.Json(
        string="Agent Hub JSON Body",
        help="Structured content: tool_calls, tool results, cards.",
    )
    agenthub_is_error = fields.Boolean(
        string="Agent Hub Error",
        default=False,
        index=True,
        help="Shown to users but excluded from agent context.",
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
        help="Legacy/audit field; the relay owns the hot delivery state.",
    )
    agenthub_relay_message_id = fields.Char(
        string="Agent Hub Relay Message ID", index=True
    )
    agenthub_relay_turn_id = fields.Char(
        string="Agent Hub Relay Turn ID", index=True
    )
    agenthub_turn_id = fields.Many2one(
        "agenthub.turn", string="Agent Hub Turn", ondelete="set null", index=True
    )
    agenthub_stream_id = fields.Char(
        string="Agent Hub Stream ID",
        index=True,
        help="Correlates the frames of one streamed reply.",
    )

    @api.model
    def get_agenthub_roles(self):
        """Return ``(id_to_role, role_to_id)`` for agenthub message subtypes."""
        id_to_role = {}
        role_to_id = {}
        for xmlid in self.AGENTHUB_XMLIDS:
            res_id = self.env["ir.model.data"]._xmlid_to_res_id(
                xmlid, raise_if_not_found=False
            )
            if res_id:
                role = xmlid.split(".")[-1][3:]
                id_to_role[res_id] = role
                role_to_id[role] = res_id
        return id_to_role, role_to_id

    def _agenthub_role_from_subtype(self):
        self.ensure_one()
        id_to_role, _ = self.get_agenthub_roles()
        return id_to_role.get(self.subtype_id.id) if self.subtype_id else False
