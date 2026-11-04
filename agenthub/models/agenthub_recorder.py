import logging
import re

from markupsafe import Markup

from odoo import _, api, fields, models
from odoo.exceptions import UserError, ValidationError
from odoo.tools import html_escape

_logger = logging.getLogger(__name__)

_ORIGIN_RE = re.compile(r"^(?P<model>[\w.]+)[,:](?P<id>\d+)$")


class AgenthubRecorder(models.AbstractModel):
    """Consume relay record-feed events into Odoo's mail.message archive."""

    _name = "agenthub.recorder"
    _description = "Agent Hub Relay Recorder"

    @api.model
    def _process_event(self, event):
        event_type = event.get("event_type")
        if event_type == "presence.changed":
            return self._process_presence(event)
        if event_type in (
            "message.created",
            "message.updated",
            "message.final",
        ):
            return self._process_message(event)
        if event_type == "command.created":
            return self._process_command(event)
        if isinstance(event_type, str) and event_type.startswith("turn."):
            return self._process_turn(event)
        if isinstance(event_type, str) and event_type.startswith("delivery."):
            return self._process_delivery(event)
        _logger.debug("agenthub recorder: ignoring event type %s", event_type)
        return None

    # -- messages -------------------------------------------------------

    def _process_message(self, event):
        event_type = event.get("event_type")
        if event_type == "message.updated":
            # Partial stream frames stay in the relay hot log; only final
            # messages are projected into mail.message.
            return None
        payload = event.get("payload") or {}
        thread = self._ensure_thread(event)
        turn = self._ensure_turn(event, thread)
        meta = event.get("meta") or {}
        origin_record_id = meta.get("origin_record_id")
        if origin_record_id:
            existing = self._message_from_origin(origin_record_id)
            if existing:
                self._link_existing_message(existing, event, thread, turn)
                return existing
        message = self._ensure_message(event, thread, turn)
        if message and payload.get("role") == "user":
            if not turn.inbound_message_id:
                turn.inbound_message_id = message
        return message

    def _ensure_thread(self, event):
        route = event.get("route") or {}
        thread_key = route.get("thread_key")
        if not thread_key:
            raise UserError(_("Recorder event has no route.thread_key"))
        thread = self.env["agenthub.thread"].search(
            [("relay_thread_key", "=", thread_key)], limit=1
        )
        if thread:
            return thread
        agent_id = route.get("agent_id")
        agent = (
            self.env["agenthub.agent"].browse(int(agent_id))
            if agent_id is not None
            else self.env["agenthub.agent"]
        )
        if not agent.exists():
            raise UserError(
                _("Recorder event references unknown agent %s") % agent_id
            )
        if thread_key.startswith("discuss.channel:"):
            discuss_id = int(thread_key.split(":", 1)[1])
            discuss = self.env["discuss.channel"].browse(discuss_id)
            if not discuss.exists():
                raise UserError(
                    _("Recorder event references unknown discuss channel %s")
                    % discuss_id
                )
            return self.env["agenthub.thread"].create(
                {
                    "name": discuss.name or thread_key,
                    "channel_id": False,
                    "peer_ref": thread_key,
                    "agent_id": agent.id,
                    "relay_thread_key": thread_key,
                    "discuss_channel_id": discuss.id,
                }
            )
        channel_id = route.get("channel_id")
        if channel_id is None:
            raise UserError(
                _("External recorder events require route.channel_id")
            )
        peer_ref = route.get("peer_ref") or thread_key
        return self.env["agenthub.thread"]._find_or_create(
            int(channel_id),
            peer_ref,
            agent.id,
            name=peer_ref,
            relay_thread_key=thread_key,
        )

    def _ensure_turn(self, event, thread):
        turn_meta = event.get("turn") or {}
        payload = event.get("payload") or {}
        relay_turn_id = turn_meta.get("turn_id") or payload.get("turn_id")
        if not relay_turn_id:
            relay_turn_id = "event:%s" % event.get("event_id")
        turn = self.env["agenthub.turn"].search(
            [("relay_turn_id", "=", relay_turn_id)], limit=1
        )
        if turn:
            return turn
        state = turn_meta.get("state") or "running"
        vals = {
            "thread_id": thread.id,
            "agent_id": thread.agent_id.id,
            "relay_turn_id": relay_turn_id,
            "state": state,
            "is_active": state
            not in ("completed", "failed", "cancelled", "expired"),
        }
        try:
            return self.env["agenthub.turn"].create(vals)
        except ValidationError:
            # The relay serializes turns; if an older turn is still active in
            # Odoo, keep this one inactive so history is not lost.
            vals["is_active"] = False
            return self.env["agenthub.turn"].create(vals)

    def _ensure_message(self, event, thread, turn):
        payload = event.get("payload") or {}
        relay_message_id = payload.get("message_id")
        if not relay_message_id:
            raise UserError(_("Recorder message event has no message_id"))
        stream_id = payload.get("stream_id")
        domain = [("agenthub_relay_message_id", "=", relay_message_id)]
        if stream_id:
            domain.append(("agenthub_stream_id", "=", stream_id))
        message = self.env["mail.message"].search(domain, limit=1)
        if message:
            self._update_message(message, event, turn)
            return message
        return self._create_message(event, thread, turn)

    def _create_message(self, event, thread, turn):
        payload = event.get("payload") or {}
        role = payload.get("role") or "assistant"
        content = payload.get("content") or ""
        body = self._render_body(content)
        author_id = self._author_id(event, thread)
        subtype_id = self._subtype_id(role)
        agenthub_vals = self._agenthub_message_vals(event, turn)
        if thread.discuss_channel_id:
            message = thread.discuss_channel_id.message_post(
                body=body,
                author_id=author_id,
                message_type="comment",
                subtype_xmlid="agenthub.mt_%s" % role,
            )
            message.write(agenthub_vals)
            return message
        vals = dict(agenthub_vals)
        vals.update(
            {
                "model": thread._name,
                "res_id": thread.id,
                "message_type": "comment",
                "subtype_id": subtype_id,
                "body": body,
                "author_id": author_id,
            }
        )
        return self.env["mail.message"].create(vals)

    def _update_message(self, message, event, turn):
        payload = event.get("payload") or {}
        message.write(
            {
                "body": self._render_body(payload.get("content") or ""),
                **self._agenthub_message_vals(event, turn),
            }
        )

    def _link_existing_message(self, message, event, thread, turn):
        payload = event.get("payload") or {}
        vals = self._agenthub_message_vals(event, turn)
        if not message.agenthub_content:
            vals["agenthub_content"] = payload.get("content") or ""
        message.write(vals)
        if payload.get("role") == "user" and not turn.inbound_message_id:
            turn.inbound_message_id = message

    def _agenthub_message_vals(self, event, turn):
        payload = event.get("payload") or {}
        role = payload.get("role") or "assistant"
        return {
            "agenthub_role": role,
            "agenthub_content": payload.get("content") or "",
            "agenthub_body_json": payload.get("body_json"),
            "agenthub_is_error": bool(payload.get("is_error", False)),
            "agenthub_relay_message_id": payload.get("message_id"),
            "agenthub_relay_turn_id": turn.relay_turn_id,
            "agenthub_turn_id": turn.id,
            "agenthub_stream_id": payload.get("stream_id"),
            "agenthub_external_id": payload.get("external_id"),
            "agenthub_reply_to_external_id": payload.get(
                "reply_to_external_id"
            ),
            "agenthub_direction": "in" if role == "user" else "out",
        }

    def _author_id(self, event, thread):
        payload = event.get("payload") or {}
        role = payload.get("role") or "assistant"
        if role == "user":
            user_id = (event.get("route") or {}).get("user_id")
            user = (
                self.env["res.users"].browse(int(user_id))
                if user_id is not None
                else self.env["res.users"]
            )
            return user.partner_id.id if user.exists() else False
        return thread.agent_id.user_id.partner_id.id

    def _subtype_id(self, role):
        subtype = self.env.ref(
            "agenthub.mt_%s" % role, raise_if_not_found=False
        )
        return subtype.id if subtype else False

    @api.model
    def _render_body(self, content):
        return Markup(html_escape(content or "").replace("\n", "<br/>"))

    def _message_from_origin(self, origin_record_id):
        match = _ORIGIN_RE.match(origin_record_id or "")
        if not match:
            return None
        if match.group("model") != "mail.message":
            return None
        message = self.env["mail.message"].browse(int(match.group("id")))
        return message if message.exists() else None

    # -- turns / deliveries / presence / commands ----------------------

    def _process_turn(self, event):
        turn_meta = event.get("turn") or {}
        payload = event.get("payload") or {}
        relay_turn_id = turn_meta.get("turn_id") or payload.get("turn_id")
        turn = self.env["agenthub.turn"].search(
            [("relay_turn_id", "=", relay_turn_id)], limit=1
        )
        if not turn:
            thread = self._ensure_thread(event)
            turn = self._ensure_turn(event, thread)
        state = payload.get("state") or {
            "turn.started": "running",
            "turn.completed": "completed",
            "turn.failed": "failed",
            "turn.cancelled": "cancelled",
        }.get(event.get("event_type"))
        if state in ("completed", "failed", "cancelled", "expired"):
            turn.write(
                {
                    "state": state,
                    "finished_at": fields.Datetime.now(),
                    "error": payload.get("error"),
                }
            )
        elif state:
            turn.write({"state": state})

    def _process_delivery(self, event):
        payload = event.get("payload") or {}
        turn_meta = event.get("turn") or {}
        relay_delivery_id = payload.get("delivery_id")
        relay_turn_id = turn_meta.get("turn_id")
        if not relay_delivery_id or not relay_turn_id:
            return
        turn = self.env["agenthub.turn"].search(
            [("relay_turn_id", "=", relay_turn_id)], limit=1
        )
        if not turn:
            return
        state = payload.get("state") or "queued"
        if state in ("done", "acked", "sent"):
            state = "done"
        elif state == "expired":
            state = "queued"
        vals = {
            "turn_id": turn.id,
            "agent_id": turn.agent_id.id,
            "channel_id": (event.get("route") or {}).get("channel_id")
            or False,
            "leg": payload.get("leg") or "to_agent",
            "relay_delivery_id": relay_delivery_id,
            "state": state,
            "attempt": payload.get("attempt") or 0,
            "error": payload.get("error"),
        }
        if state == "done":
            vals["sent_at"] = fields.Datetime.now()
        delivery = self.env["agenthub.delivery"].search(
            [("relay_delivery_id", "=", relay_delivery_id)], limit=1
        )
        if delivery:
            delivery.write(vals)
        else:
            self.env["agenthub.delivery"].create(vals)

    def _process_presence(self, event):
        payload = event.get("payload") or {}
        agent_id = payload.get("agent_id")
        if agent_id is None:
            return
        agent = self.env["agenthub.agent"].browse(int(agent_id))
        if not agent.exists():
            return
        mapping = {
            "online": "online",
            "busy": "busy",
            "offline": "offline",
            "connecting": "offline",
            "draining": "offline",
        }
        agent.write(
            {
                "state": mapping.get(payload.get("state"), "offline"),
                "last_seen": fields.Datetime.now(),
            }
        )

    def _process_command(self, event):
        meta = event.get("meta") or {}
        if meta.get("origin") == "odoo":
            return
        payload = event.get("payload") or {}
        route = event.get("route") or {}
        command_id = payload.get("command_id")
        agent_id = route.get("agent_id")
        if not command_id or agent_id is None:
            return
        vals = {
            "relay_command_id": command_id,
            "name": payload.get("name") or command_id,
            "agent_id": int(agent_id),
            "payload": payload.get("payload"),
            "reply_mode": payload.get("reply_mode") or "none",
            "state": "queued",
        }
        command = self.env["agenthub.command"].search(
            [("relay_command_id", "=", command_id)], limit=1
        )
        if command:
            command.write(vals)
        else:
            self.env["agenthub.command"].create(vals)
