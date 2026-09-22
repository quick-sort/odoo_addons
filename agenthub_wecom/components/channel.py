"""WeCom transport adapter for ``agenthub.channel``."""

from odoo.exceptions import UserError
from odoo.tools import html2plaintext

from odoo.addons.component.core import Component

from ..services.aibot import build_message_callback, registry


class AgenthubChannelWecom(Component):
    _name = "agenthub.channel.wecom"
    _inherit = "agenthub.channel.adapter"
    _usage = "wecom"

    def send(self, channel, message):
        """Deliver an outbound ``mail.message`` to the connected bot."""
        connection = registry.get(channel.bot_id)
        if connection is None:
            raise UserError(
                "WeCom bot %s is not connected." % (channel.bot_id or "<none>")
            )
        frame = build_message_callback(
            msgid=message.agenthub_external_id or str(message.id),
            aibotid=channel.bot_id,
            chattype="single",
            userid=channel.bot_id,
            text=html2plaintext(message.body or ""),
        )
        connection.send(frame)
