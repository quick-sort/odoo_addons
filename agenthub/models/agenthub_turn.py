from odoo import _, api, fields, models
from odoo.exceptions import ValidationError


class AgenthubTurn(models.Model):
    """One question/command -> agent run -> reply."""

    _name = "agenthub.turn"
    _description = "Agent Hub Turn"
    _order = "id desc"

    STATE_SELECTION = [
        ("queued", "Queued"),
        ("running", "Running"),
        ("completed", "Completed"),
        ("failed", "Failed"),
        ("cancelled", "Cancelled"),
        ("expired", "Expired"),
    ]
    TERMINAL_STATES = frozenset(
        {"completed", "failed", "cancelled", "expired"}
    )

    thread_id = fields.Many2one(
        "agenthub.thread", required=True, ondelete="cascade", index=True
    )
    agent_id = fields.Many2one(
        "agenthub.agent", required=True, ondelete="restrict", index=True
    )
    inbound_message_id = fields.Many2one(
        "mail.message", ondelete="set null", index=True
    )
    relay_turn_id = fields.Char(required=True, index=True)
    state = fields.Selection(
        STATE_SELECTION, default="queued", required=True, index=True
    )
    attempt = fields.Integer(default=0)
    started_at = fields.Datetime()
    finished_at = fields.Datetime()
    error = fields.Text()
    is_active = fields.Boolean(default=True, index=True)

    _turn_uniq = models.Constraint(
        "UNIQUE(relay_turn_id)",
        "Relay turn id must be unique.",
    )

    @api.constrains("thread_id", "is_active")
    def _check_single_active_turn(self):
        for turn in self:
            if not turn.is_active:
                continue
            duplicate = self.search_count(
                [
                    ("thread_id", "=", turn.thread_id.id),
                    ("is_active", "=", True),
                    ("id", "!=", turn.id),
                ]
            )
            if duplicate:
                raise ValidationError(
                    _(
                        "Thread '%s' already has an active turn.",
                        turn.thread_id.display_name,
                    )
                )

    def write(self, vals):
        if vals.get("state") in self.TERMINAL_STATES:
            vals["is_active"] = False
        return super().write(vals)
