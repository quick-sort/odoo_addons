import logging

from odoo import _, models

_logger = logging.getLogger(__name__)


class DiscussChannel(models.Model):
    _inherit = "discuss.channel"

    def _message_post_after_hook(self, message, msg_vals):
        # Capture eligibility before mail_bot runs. The final onboarding message
        # changes odoobot_state to idle inside super(), but must not also become
        # the first LLM prompt.
        odoobot_agent = self._llm_discuss_odoobot_takeover_agent(msg_vals)
        result = super()._message_post_after_hook(message, msg_vals)

        try:
            self.env["llm.agent"]._llm_discuss_dispatch(
                self,
                message,
                msg_vals,
            )
        except Exception:  # noqa: BLE001 - never roll back an authorized user message
            _logger.exception(
                "llm_discuss: failed to dispatch message %s on channel %s",
                message.id,
                self.id,
            )

        if odoobot_agent:
            try:
                odoobot_agent._llm_discuss_dispatch_odoobot(self, message)
            except Exception:  # noqa: BLE001 - never roll back an authorized user message
                _logger.exception(
                    "llm_discuss: failed to dispatch OdooBot message %s on channel %s",
                    message.id,
                    self.id,
                )
        return result

    def _llm_discuss_user_can_use_agent(self, agent, user):
        """Check agent availability for the message sender.

        The Live Chat bridge overrides this for a visitor talking to the bot
        selected as that session's operator.
        """
        self.ensure_one()
        if not user.has_group("base.group_user"):
            return bool(agent.is_public)
        allowed = agent.sudo()._get_allowed_agents_for_user(user)
        return agent in allowed

    def _llm_discuss_should_trigger(self, agent, message, msg_vals):
        """Return whether ``agent`` should reply to this channel message."""
        self.ensure_one()
        bot_partner = agent.discuss_user_id.partner_id
        if not bot_partner or message.author_id == bot_partner:
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

    def _llm_discuss_odoobot_takeover_agent(self, msg_vals):
        """Return the configured agent for an eligible post-onboarding chat."""
        self.ensure_one()
        source_user = self.env.user
        odoobot_partner = self.env.ref("base.partner_root")
        body = (msg_vals.get("body") or "").replace("\xa0", " ").strip().lower().strip(".!")
        restarts_native_tour = (
            source_user.odoobot_state == "idle"
            and _("start the tour") in body
        )
        if (
            not source_user.has_group("base.group_user")
            or source_user.odoobot_state not in {"idle", "disabled"}
            or restarts_native_tour
            or msg_vals.get("author_id") == odoobot_partner.id
            or msg_vals.get("message_type", "notification") != "comment"
            or self.channel_type != "chat"
        ):
            return self.env["llm.agent"]

        member_partner_ids = set(self.channel_member_ids.partner_id.ids)
        expected_partner_ids = {odoobot_partner.id, source_user.partner_id.id}
        if member_partner_ids != expected_partner_ids:
            return self.env["llm.agent"]

        agent = self.env["llm.agent"]._get_odoobot_agent()
        if not agent or not self._llm_discuss_user_can_use_agent(
            agent,
            source_user,
        ):
            return self.env["llm.agent"]
        return agent
