import logging

from odoo import models
from odoo.tools import html2plaintext

_logger = logging.getLogger(__name__)


class DiscussChannel(models.Model):
    _inherit = "discuss.channel"

    def _message_post_after_hook(self, message, msg_vals):
        result = super()._message_post_after_hook(message, msg_vals)
        try:
            self._agenthub_publish_inbound(message)
        except Exception:  # noqa: BLE001 - a failed publish must not undo the post
            _logger.exception(
                "agenthub_discuss: failed to publish message %s", message.id
            )
        return result

    def _agenthub_publish_inbound(self, message):
        self.ensure_one()
        if message.message_type not in ("comment", "email"):
            return
        thread = (
            self.env["agenthub.thread"]
            .sudo()
            .search(
                [
                    ("discuss_channel_id", "=", self.id),
                    ("state", "=", "active"),
                ],
                limit=1,
            )
        )
        if not thread:
            return
        author = message.author_id
        if not author:
            return
        odoobot = self.env.ref("base.partner_root", raise_if_not_found=False)
        if odoobot and author == odoobot:
            return
        if author == thread.agent_id.user_id.partner_id:
            return
        user = author.user_ids[:1]
        if not user:
            return
        content = html2plaintext(message.body or "").strip()
        if not content:
            return
        thread_key = "discuss.channel:%s" % self.id
        self.env["agenthub.publish"]._enqueue(
            "message.created",
            {
                "message_id": "odoo:mail.message:%s" % message.id,
                "role": "user",
                "content": content,
                "final": True,
                "author": {"type": "user", "id": user.id},
                "external_id": str(message.id),
            },
            event_id="odoo:mail.message:%s:message.created" % message.id,
            route={
                "agent_id": thread.agent_id.id,
                "thread_key": thread_key,
                "peer_ref": thread_key,
                "user_id": user.id,
            },
            turn={},
            meta={
                "origin": "odoo",
                "origin_record_id": "mail.message,%s" % message.id,
            },
        )
