from odoo import _, api, fields, models
from odoo.exceptions import UserError


class AgenthubCommand(models.Model):
    """System/cron command dispatched to an agent."""

    _name = "agenthub.command"
    _description = "Agent Hub Command"
    _order = "id desc"

    name = fields.Char(required=True)
    agent_id = fields.Many2one(
        "agenthub.agent", required=True, ondelete="cascade", index=True
    )
    thread_id = fields.Many2one(
        "agenthub.thread", ondelete="set null", index=True
    )
    relay_command_id = fields.Char(index=True)
    payload = fields.Json()
    reply_mode = fields.Selection(
        [
            ("none", "Store Only"),
            ("owner", "Notify Owner"),
            ("thread", "Reply To Thread"),
        ],
        default="none",
        required=True,
    )
    state = fields.Selection(
        [
            ("draft", "Draft"),
            ("queued", "Queued"),
            ("sent", "Sent"),
            ("running", "Running"),
            ("completed", "Completed"),
            ("failed", "Failed"),
            ("cancelled", "Cancelled"),
        ],
        default="draft",
        required=True,
        index=True,
    )
    result_message_id = fields.Many2one("mail.message", ondelete="set null")
    active = fields.Boolean(default=True)

    @api.model_create_multi
    def create(self, vals_list):
        commands = super().create(vals_list)
        for command in commands:
            if command.state == "queued":
                command._enqueue_publish()
        return commands

    def write(self, vals):
        result = super().write(vals)
        if vals.get("state") == "queued":
            self._enqueue_publish()
        return result

    def action_queue(self):
        self.write({"state": "queued"})
        return True

    def _enqueue_publish(self):
        for command in self:
            if not command.agent_id:
                continue
            thread_key = (
                command.thread_id.relay_thread_key
                if command.thread_id
                else None
            )
            if command.reply_mode == "thread" and not thread_key:
                raise UserError(
                    _("reply_mode 'thread' requires a thread with a relay key.")
                )
            if not command.relay_command_id:
                command.relay_command_id = "odoo:command:%s" % command.id
            self.env["agenthub.publish"]._enqueue(
                "command.created",
                {
                    "command_id": command.relay_command_id,
                    "name": command.name,
                    "payload": command.payload or {},
                    "reply_mode": command.reply_mode,
                    "thread_key": thread_key,
                    "created_by": command.create_uid.id,
                },
                event_id="odoo:command:%s:command.created" % command.id,
                route={
                    "agent_id": command.agent_id.id,
                    "thread_key": thread_key,
                    "reply_mode": command.reply_mode,
                },
                turn={},
                meta={
                    "origin": "odoo",
                    "origin_record_id": "agenthub.command,%s" % command.id,
                },
            )
