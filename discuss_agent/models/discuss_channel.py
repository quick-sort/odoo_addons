import logging

from odoo import models

_logger = logging.getLogger(__name__)


class DiscussChannel(models.Model):
    _inherit = "discuss.channel"

    def _message_post_after_hook(self, message, msg_vals):
        result = super()._message_post_after_hook(message, msg_vals)
        try:
            self.env["discuss.agent"]._discuss_dispatch(self, message, msg_vals)
        except Exception:  # noqa: BLE001 - never roll back an authorized user message
            _logger.exception(
                "discuss_agent: failed to dispatch message %s on channel %s",
                message.id,
                self.id,
            )
        return result

    def _discuss_user_can_use_agent(self, agent, user):
        """Return whether ``user`` may have ``agent`` reply to them.

        MVP: any internal user may use any enabled agent. Bridge addons
        (portal / live chat / per-agent ACL) override this.
        """
        self.ensure_one()
        return bool(user.has_group("base.group_user"))

    def _discuss_should_trigger(self, agent, message, msg_vals):
        """Return whether ``agent`` should reply to this channel message."""
        self.ensure_one()
        bot_partner = agent.discuss_user_id.partner_id
        if not bot_partner or message.author_id.id == bot_partner.id:
            return False
        if msg_vals.get("message_type", "notification") != "comment":
            return False

        is_direct_chat = (
            self.channel_type == "chat"
            and bot_partner in self.channel_member_ids.partner_id
        )
        is_mentioned = bot_partner.id in (msg_vals.get("partner_ids") or [])

        mode = agent.discuss_trigger_mode
        if mode == "direct_chat":
            return is_direct_chat
        if mode == "mention":
            return is_mentioned
        return is_direct_chat or is_mentioned
